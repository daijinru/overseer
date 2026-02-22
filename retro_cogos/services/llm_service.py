"""LLM service — calls LLM API and parses structured decisions."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from retro_cogos.config import get_config
from retro_cogos.core.protocols import HelpRequest, LLMDecision, TaskPlan, ToolCall, WorkingMemory

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
你是 Retro CogOS（认知操作系统）的认知引擎。

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
  "reflection": "简短反思",
  "help_request": null,
  "subtask_complete": false
}
```

规则：
- 当你需要用户做出选择、提供信息或确认关键操作时，设置 "human_required": true，在 "human_reason" 中解释原因，并提供 "options"。
- 当目标已完全达成时，**不要直接**设置 "task_complete": true。而是先设置 "human_required": true，在 "human_reason" 中提供完整的任务总结报告（包括：完成了哪些工作、关键产出物、遇到的问题及处理方式），并提供 "options": ["确认完成", "补充修改"]。只有当用户确认完成后，才在下一步设置 "task_complete": true。human_reason 中的总结报告不受 200 字限制。
- 使用 "tool_calls" 来调用工具。每个 tool_call 格式为 {"tool": "工具名", "args": {参数}}。tool 字段必须是可用工具列表中的精确工具名。
- **严格遵守工具参数**：只使用 Available Tools 中列出的参数名。不要自行发明或添加未定义的参数（如 "query"），未定义的参数会被系统丢弃。
- **避免重复调用**：如果一个工具已经调用过且结果不理想，不要用相同参数再次调用。应改用其他工具或请求用户帮助。
- 反思时，诚实评估你是否在朝目标推进。

求助协议：
- 当你缺少关键信息、尝试了多种方法仍无法推进时，使用 "help_request" 字段明确说明：
  - missing_information: 你缺少哪些具体信息
  - attempted_approaches: 你已经尝试了哪些方法
  - specific_question: 你想问用户的具体问题
  - suggested_human_actions: 建议用户可以做什么来帮助你
- 请求帮助不是失败，而是高效的问题解决策略。主动求助优于盲目尝试。

子任务协议：
- 如果当前上下文包含 "Current Subtask"，请围绕该子任务工作。
- 当子任务的成功标准已满足时，设置 "subtask_complete": true。
- 不要越界处理其他子任务的内容。
"""


PLANNING_SYSTEM_PROMPT = """\
你是 Retro CogOS 的规划引擎。你的职责是将一个复杂目标分解为可执行的子任务序列。

请分析目标，考虑可用工具，制定一个清晰的执行计划。

输出格式：用 ```plan``` 围栏包裹一个 JSON 块。

```plan
{
  "subtasks": [
    {
      "id": 1,
      "title": "子任务标题",
      "description": "具体描述做什么、怎么做",
      "success_criteria": "如何判断这个子任务已完成",
      "suggested_tools": ["推荐使用的工具名"],
      "estimated_steps": 3
    }
  ],
  "risks": ["可能遇到的风险或困难"],
  "overall_strategy": "总体执行策略的简要描述"
}
```

规则：
- 子任务数量控制在 3-10 个，每个子任务应该是 1-5 步可完成的。
- 子任务之间应有清晰的顺序依赖关系。
- suggested_tools 只填写 Available Tools 中存在的工具名。
- success_criteria 要具体可验证，不要用模糊描述。
- 全程使用中文。
"""


CHECKPOINT_SYSTEM_PROMPT = """\
你是 Retro CogOS 的检查点评估器。一个子任务刚刚完成，请评估整体进展并决定是否需要调整计划。

请用 ```checkpoint``` 围栏包裹一个 JSON 块。

```checkpoint
{
  "progress_assessment": "对已完成工作的简要评估",
  "plan_still_valid": true,
  "revision": null
}
```

如果需要修订计划（如发现新的子任务需要插入、某些子任务可以跳过等），将 "plan_still_valid" 设为 false，并在 "revision" 中提供修订后的完整 subtasks 列表。

规则：
- 评估要简洁（不超过 100 字）。
- 只有在确实需要时才修订计划，不要为了修订而修订。
- 全程使用中文。
"""


COMPRESSION_PROMPT = """\
你是 Retro CogOS 的记忆压缩器。请将以下执行历史压缩为一份简洁的工作记忆摘要。

请用 ```memory``` 围栏包裹一个 JSON 块。

```memory
{
  "summary": "2-3 句话概括目前的工作进展",
  "key_findings": ["关键发现 1", "关键发现 2"],
  "failed_approaches": ["失败方法 1：原因"],
  "open_questions": ["待解决的问题"]
}
```

规则：
- summary 不超过 150 字。
- key_findings 保留最重要的 3-5 条。
- failed_approaches 必须保留，这是防止重复犯错的关键信息。
- 丢弃冗余的中间步骤细节，只保留结论性信息。
- 全程使用中文。
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
        """Build LLMDecision from a dict, normalising tool_calls and help_request."""
        raw_tcs = data.pop("tool_calls", [])
        raw_help = data.pop("help_request", None)
        raw_plan_rev = data.pop("plan_revision", None)
        decision = LLMDecision(**data)
        decision.tool_calls = [ToolCall.from_llm(tc) for tc in raw_tcs]
        if raw_help and isinstance(raw_help, dict):
            decision.help_request = HelpRequest(**raw_help)
        if raw_plan_rev and isinstance(raw_plan_rev, dict):
            decision.plan_revision = TaskPlan(**raw_plan_rev)
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

    async def plan(self, prompt: str) -> str:
        """Call LLM with the planning system prompt to generate a task plan."""
        messages = [
            {"role": "system", "content": PLANNING_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        payload: Dict[str, Any] = {
            "model": self._cfg.model,
            "messages": messages,
            "max_tokens": self._cfg.max_tokens,
            "temperature": self._cfg.temperature,
        }
        url = f"{self._cfg.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._cfg.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"]

    def parse_plan(self, response: str) -> Optional[TaskPlan]:
        """Extract a TaskPlan from a ```plan``` fenced block."""
        pattern = r"```plan\s*\n(.*?)\n```"
        match = re.search(pattern, response, re.DOTALL)
        if match:
            try:
                return TaskPlan(**json.loads(match.group(1)))
            except (json.JSONDecodeError, Exception) as e:
                logger.warning("Failed to parse plan block: %s", e)
        return None

    async def compress(self, prompt: str) -> str:
        """Call LLM with the compression system prompt to summarize context."""
        messages = [
            {"role": "system", "content": COMPRESSION_PROMPT},
            {"role": "user", "content": prompt},
        ]
        payload: Dict[str, Any] = {
            "model": self._cfg.model,
            "messages": messages,
            "max_tokens": 1024,
            "temperature": 0.3,
        }
        url = f"{self._cfg.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._cfg.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"]

    def parse_working_memory(self, response: str) -> Optional[WorkingMemory]:
        """Extract a WorkingMemory from a ```memory``` fenced block."""
        pattern = r"```memory\s*\n(.*?)\n```"
        match = re.search(pattern, response, re.DOTALL)
        if match:
            try:
                return WorkingMemory(**json.loads(match.group(1)))
            except (json.JSONDecodeError, Exception) as e:
                logger.warning("Failed to parse memory block: %s", e)
        return None

    async def checkpoint(self, prompt: str) -> str:
        """Call LLM with the checkpoint system prompt for subtask-boundary review."""
        messages = [
            {"role": "system", "content": CHECKPOINT_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        payload: Dict[str, Any] = {
            "model": self._cfg.model,
            "messages": messages,
            "max_tokens": 1024,
            "temperature": 0.3,
        }
        url = f"{self._cfg.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._cfg.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"]

    def parse_checkpoint(self, response: str) -> Dict[str, Any]:
        """Extract checkpoint assessment from a ```checkpoint``` fenced block."""
        pattern = r"```checkpoint\s*\n(.*?)\n```"
        match = re.search(pattern, response, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except (json.JSONDecodeError, Exception) as e:
                logger.warning("Failed to parse checkpoint block: %s", e)
        return {"progress_assessment": "", "plan_still_valid": True, "revision": None}
