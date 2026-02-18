"""LLM service — calls LLM API and parses structured decisions."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from ceo.config import get_config
from ceo.core.protocols import LLMDecision, ToolCall

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
你是 Wenko CEO（认知操作系统）的认知引擎。

你的职责：根据给定的目标和已积累的上下文，决定下一步该做什么。

重要：请全程使用中文回复。每个回复必须以一个 JSON 决策块结尾，用 ```decision``` 围栏包裹。

输出格式要求（严格遵守）：
1. 分析部分要精简，不超过 200 字，聚焦于可操作的洞察。
2. decision 块中的字段值要简短：title 不超过 20 字，description 不超过 50 字，reflection 不超过 100 字。
3. 禁止在 decision 块中放置大段文本，详细内容放在分析部分。
4. 必须确保 decision 块 JSON 完整闭合，这是最高优先级。

```decision
{
  "next_action": {"title": "简短标题", "description": "简短描述"},
  "tool_calls": [],
  "human_required": false,
  "human_reason": null,
  "options": [],
  "task_complete": false,
  "confidence": 0.8,
  "reflection": "简短反思"
}
```

规则：
- 当你需要用户做出选择、提供信息或确认关键操作时，设置 "human_required": true，在 "human_reason" 中解释原因，并提供 "options"。
- 当目标已完全达成时，**不要直接**设置 "task_complete": true。而是先设置 "human_required": true，在 "human_reason" 中提供完整的任务总结报告（包括：完成了哪些工作、关键产出物、遇到的问题及处理方式），并提供 "options": ["确认完成", "补充修改"]。只有当用户确认完成后，才在下一步设置 "task_complete": true。human_reason 中的总结报告不受 200 字限制。
- 使用 "tool_calls" 来调用工具。每个 tool_call 格式为 {"tool": "工具名", "args": {参数}}。tool 字段必须是可用工具列表中的精确工具名。
- **严格遵守工具参数**：只使用 Available Tools 中列出的参数名。不要自行发明或添加未定义的参数（如 "query"），未定义的参数会被系统丢弃。
- **避免重复调用**：如果一个工具已经调用过且结果不理想，不要用相同参数再次调用。应改用其他工具或请求用户帮助。
- 反思时，诚实评估你是否在朝目标推进。
"""


class LLMService:
    def __init__(self):
        self._cfg = get_config().llm

    async def call(
        self,
        prompt: str,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Call LLM and return raw response text."""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        payload: Dict[str, Any] = {
            "model": self._cfg.model,
            "messages": messages,
            "max_tokens": self._cfg.max_tokens,
            "temperature": self._cfg.temperature,
        }
        if tools:
            payload["tools"] = tools

        url = f"{self._cfg.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._cfg.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"]
        return content

    def _normalize_decision(self, data: dict) -> LLMDecision:
        """Build LLMDecision from a dict, normalising tool_calls field names."""
        raw_tcs = data.pop("tool_calls", [])
        decision = LLMDecision(**data)
        decision.tool_calls = [ToolCall.from_llm(tc) for tc in raw_tcs]
        return decision

    def parse_decision(self, response: str) -> LLMDecision:
        """Extract the decision JSON block from LLM response."""
        # Try to find ```decision ... ``` block
        pattern = r"```decision\s*\n(.*?)\n```"
        match = re.search(pattern, response, re.DOTALL)
        if match:
            try:
                return self._normalize_decision(json.loads(match.group(1)))
            except (json.JSONDecodeError, Exception) as e:
                logger.warning("Failed to parse decision block: %s", e)

        # Fallback: try to find any JSON block that looks like a decision
        json_pattern = r"\{[^{}]*\"task_complete\"[^{}]*\}"
        match = re.search(json_pattern, response, re.DOTALL)
        if match:
            try:
                return self._normalize_decision(json.loads(match.group(0)))
            except (json.JSONDecodeError, Exception):
                pass

        # Last resort: return a default decision that asks for human help
        logger.warning("Could not parse decision from LLM response, requesting human input")
        return LLMDecision(
            human_required=True,
            human_reason="无法确定下一步操作，请查看回复内容并给予指引。",
            options=["继续", "终止"],
        )

    async def reflect(self, context: dict) -> str:
        """Ask LLM to reflect on progress so far."""
        prompt = f"""请回顾以下任务上下文，反思当前进展。

上下文：
{json.dumps(context, ensure_ascii=False, indent=2)}

请用中文给出简要反思，以 JSON 格式输出：
```decision
{{
  "next_action": {{"title": "反思", "description": "对进展的自我评估"}},
  "tool_calls": [],
  "human_required": false,
  "task_complete": false,
  "confidence": 0.5,
  "reflection": "你的诚实评估"
}}
```"""
        return await self.call(prompt)
