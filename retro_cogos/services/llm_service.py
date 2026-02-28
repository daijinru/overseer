"""LLM service — calls LLM API and parses structured decisions."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional

import httpx

from retro_cogos.config import get_config
from retro_cogos.core.protocols import LLMDecision, TaskPlan, WorkingMemory

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

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

# NOTE: SYSTEM_PROMPT above is kept only as a fallback default for
# LLMService.call() when no system_prompt is explicitly provided
# (e.g. direct usage outside the orchestration loop).
# The canonical, security-authoritative copy lives in
# kernel/firewall_engine.py → PromptPolicy.
# In the orchestration loop, ExecutionService always passes
# FirewallEngine.get_system_prompt() via the system_prompt parameter.


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
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily create a persistent async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=120.0)
        return self._client

    async def close(self) -> None:
        """Close the persistent HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        messages: List[Dict[str, Any]],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Unified HTTP request with retry and optional streaming.

        Retry uses exponential backoff for transient errors (429/5xx)
        and honours the Retry-After header for 429 responses.
        """
        payload: Dict[str, Any] = {
            "model": self._cfg.model,
            "messages": messages,
            "max_tokens": max_tokens or self._cfg.max_tokens,
            "temperature": temperature if temperature is not None else self._cfg.temperature,
        }
        if tools:
            payload["tools"] = tools
        if stream:
            payload["stream"] = True

        url = f"{self._cfg.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._cfg.api_key}",
            "Content-Type": "application/json",
        }

        max_retries = self._cfg.max_retries
        base_delay = self._cfg.retry_base_delay
        max_delay = self._cfg.retry_max_delay
        last_error: Exception | None = None

        for attempt in range(1, max_retries + 1):
            try:
                client = await self._get_client()

                if stream:
                    return await self._stream_request(
                        client, url, payload, headers, on_chunk,
                    )
                else:
                    resp = await client.post(url, json=payload, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                    return data["choices"][0]["message"]["content"]

            except httpx.HTTPStatusError as e:
                last_error = e
                status_code = e.response.status_code
                if status_code not in _RETRYABLE_STATUS_CODES:
                    raise

                if status_code == 429:
                    retry_after = e.response.headers.get("Retry-After")
                    if retry_after:
                        try:
                            delay = min(float(retry_after), max_delay)
                        except ValueError:
                            delay = base_delay * (2 ** (attempt - 1))
                    else:
                        delay = base_delay * (2 ** (attempt - 1))
                else:
                    delay = base_delay * (2 ** (attempt - 1))

                delay = min(delay, max_delay)
                logger.warning(
                    "LLM API error %d (attempt %d/%d), retrying in %.1fs: %s",
                    status_code, attempt, max_retries, delay, e,
                )
                if attempt < max_retries:
                    await asyncio.sleep(delay)
                    continue

            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as e:
                last_error = e
                delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                logger.warning(
                    "LLM network error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt, max_retries, delay, e,
                )
                if attempt < max_retries:
                    await asyncio.sleep(delay)
                    await self.close()
                    continue

        raise last_error or RuntimeError("LLM request failed after all retries")

    async def _stream_request(
        self,
        client: httpx.AsyncClient,
        url: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Handle an SSE streaming request, returning the full accumulated text."""
        full_response = ""
        in_decision_block = False
        # Buffer for detecting decision markers split across chunks
        _MARKER = "```decision"
        _CLOSE = "```"

        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    delta = data.get("choices", [{}])[0].get("delta", {})
                    chunk_text = delta.get("content", "")
                except (json.JSONDecodeError, IndexError, KeyError):
                    continue
                if not chunk_text:
                    continue

                full_response += chunk_text

                # Detect entering/exiting a decision block
                if not in_decision_block and _MARKER in full_response[
                    max(0, len(full_response) - len(chunk_text) - len(_MARKER)):
                ]:
                    in_decision_block = True
                elif in_decision_block:
                    after_marker = full_response[full_response.rfind(_MARKER) + len(_MARKER):]
                    if _CLOSE in after_marker:
                        in_decision_block = False

                # Forward visible chunks to callback (suppress decision block)
                if on_chunk and not in_decision_block:
                    on_chunk(chunk_text)

        return full_response

    async def call(
        self,
        prompt: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        *,
        system_prompt: Optional[str] = None,
        stream: bool = False,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Call LLM and return raw response text."""
        messages = [
            {"role": "system", "content": system_prompt or SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        return await self._request(
            messages, tools=tools, stream=stream, on_chunk=on_chunk,
        )

    def _normalize_decision(self, data: dict) -> LLMDecision:
        """Backward-compat wrapper — delegates to FirewallEngine."""
        from retro_cogos.kernel.firewall_engine import FirewallEngine
        from retro_cogos.kernel.perception_bus import PerceptionBus
        from retro_cogos.config import get_config
        engine = FirewallEngine(get_config(), PerceptionBus())
        return engine._normalize_decision(data)

    def parse_decision(self, response: str) -> LLMDecision:
        """Extract the decision JSON block from LLM response.

        Backward-compat wrapper — delegates to FirewallEngine.parse_decision().
        Canonical implementation (with fail-safe) lives in the kernel.
        """
        from retro_cogos.kernel.firewall_engine import FirewallEngine
        from retro_cogos.kernel.perception_bus import PerceptionBus
        from retro_cogos.config import get_config
        engine = FirewallEngine(get_config(), PerceptionBus())
        return engine.parse_decision(response)

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
        return await self._request(messages)

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
        return await self._request(messages, max_tokens=1024, temperature=0.3)

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
        return await self._request(messages, max_tokens=1024, temperature=0.3)

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
