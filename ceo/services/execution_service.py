"""Execution service — the core orchestration engine (cognitive loop)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Dict, Optional

from sqlalchemy.orm import Session

from ceo.core.enums import COStatus, ExecutionStatus
from ceo.core.protocols import LLMDecision, ToolCall
from ceo.database import get_session
from ceo.models.cognitive_object import CognitiveObject
from ceo.models.execution import Execution
from ceo.services.artifact_service import ArtifactService
from ceo.services.cognitive_object_service import CognitiveObjectService
from ceo.services.context_service import ContextService
from ceo.services.llm_service import LLMService
from ceo.services.memory_service import MemoryService
from ceo.services.tool_service import ToolService
from ceo.config import get_config

logger = logging.getLogger(__name__)


class ExecutionService:
    """Core orchestration engine that drives the cognitive loop."""

    def __init__(self, session: Session | None = None):
        self._session = session
        self.co_service = CognitiveObjectService(session)
        self.context_service = ContextService(session)
        self.memory_service = MemoryService(session)
        self.artifact_service = ArtifactService(session)
        self.llm_service = LLMService()
        self.tool_service = ToolService()

        # Human-in-the-loop synchronization
        self._human_event = asyncio.Event()
        self._human_response: Dict[str, Any] = {}

        # Callbacks for TUI communication
        self._on_step_update: Optional[Callable] = None
        self._on_human_required: Optional[Callable] = None
        self._on_tool_confirm: Optional[Callable] = None
        self._on_complete: Optional[Callable] = None
        self._on_error: Optional[Callable] = None
        self._on_info: Optional[Callable] = None

    @property
    def session(self) -> Session:
        if self._session is None:
            self._session = get_session()
        return self._session

    def set_callbacks(
        self,
        on_step_update: Optional[Callable] = None,
        on_human_required: Optional[Callable] = None,
        on_tool_confirm: Optional[Callable] = None,
        on_complete: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        on_info: Optional[Callable] = None,
    ) -> None:
        """Set callback functions for TUI communication."""
        self._on_step_update = on_step_update
        self._on_human_required = on_human_required
        self._on_tool_confirm = on_tool_confirm
        self._on_complete = on_complete
        self._on_error = on_error
        self._on_info = on_info

    def provide_human_response(self, decision: str, text: str = "") -> None:
        """Called by TUI when human makes a decision."""
        self._human_response = {"decision": decision, "text": text}
        self._human_event.set()

    async def _wait_for_human(self) -> Dict[str, Any]:
        """Wait for human decision."""
        self._human_event.clear()
        await self._human_event.wait()
        response = self._human_response.copy()
        self._human_response = {}
        return response

    def _drain_mcp_stderr(self, co_id: str) -> None:
        """Forward any new MCP subprocess stderr lines to the TUI."""
        lines = self.tool_service.drain_stderr()
        if lines and self._on_info:
            for line in lines:
                self._on_info(co_id, line)

    async def run_loop(self, co_id: str) -> None:
        """Main cognitive loop for a CognitiveObject."""
        co = self.co_service.get(co_id)
        if co is None:
            logger.error("CognitiveObject not found: %s", co_id)
            return

        # Connect to MCP servers (discovers remote tools)
        try:
            mcp_lines = await self.tool_service.connect()
            if mcp_lines and self._on_info:
                for line in mcp_lines:
                    self._on_info(co_id, line)
        except Exception as e:
            logger.warning("MCP connection failed, using builtin tools: %s", e)

        # Set status to running
        self.co_service.update_status(co_id, COStatus.RUNNING)
        step_number = (co.context or {}).get("step_count", 0)
        _last_tool_sig: str | None = None  # for exact loop detection
        _repeat_count = 0
        _last_tool_names: str | None = None  # for same-tool-name detection
        _name_repeat_count = 0

        try:
            while True:
                step_number += 1
                co = self.co_service.get(co_id)  # refresh

                # Drain any new MCP stderr output and forward to TUI
                self._drain_mcp_stderr(co_id)

                # 1. Create Execution record
                execution = Execution(
                    cognitive_object_id=co_id,
                    sequence_number=step_number,
                    status=ExecutionStatus.RUNNING_LLM,
                )
                self.session.add(execution)
                self.session.commit()
                self.session.refresh(execution)

                # Notify TUI
                if self._on_step_update:
                    self._on_step_update(execution, "running_llm")

                # 2. Build prompt with context and memories
                memories = self.memory_service.retrieve_as_text(
                    co.title + " " + co.description, limit=3
                )
                available_tools = self.tool_service.list_tools()
                prompt = self.context_service.build_prompt(co, memories, available_tools)
                execution.prompt = prompt
                self.session.commit()

                # 3. Call LLM
                try:
                    response = await self.llm_service.call(prompt)
                except Exception as e:
                    logger.error("LLM call failed at step %d: %s", step_number, e)
                    execution.status = ExecutionStatus.FAILED
                    execution.llm_response = f"LLM Error: {e}"
                    self.session.commit()
                    if self._on_error:
                        self._on_error(str(e))
                    # Pause the CO so user can retry later
                    self.co_service.update_status(co_id, COStatus.PAUSED)
                    await self.tool_service.disconnect()
                    return

                execution.llm_response = response
                self.session.commit()

                # 4. Parse decision
                decision = self.llm_service.parse_decision(response)
                execution.llm_decision = decision.model_dump()
                if decision.next_action:
                    execution.title = decision.next_action.title
                else:
                    execution.title = f"Step {step_number}"
                self.session.commit()

                # Notify TUI with LLM response
                if self._on_step_update:
                    self._on_step_update(execution, "llm_done")

                # 5. Handle tool calls
                if decision.tool_calls:
                    # Pre-filter args to match what tools actually accept.
                    # Track which params were removed so we can inform LLM via context.
                    _removed_params: dict[str, list[str]] = {}
                    for tc in decision.tool_calls:
                        filtered_args, removed = self.tool_service.filter_args(tc.tool, tc.args)
                        if removed:
                            _removed_params[tc.tool] = removed
                            logger.info(
                                "Pre-filtered args for %s: removed %s",
                                tc.tool, removed,
                            )
                        tc.args = filtered_args

                    # Loop detection on filtered args
                    tool_sig = json.dumps(
                        [{"t": tc.tool, "a": tc.args} for tc in decision.tool_calls],
                        sort_keys=True,
                    )
                    if tool_sig == _last_tool_sig:
                        _repeat_count += 1
                    else:
                        _repeat_count = 0
                        _last_tool_sig = tool_sig

                    # Same-tool-name detection (same tools called, even if args differ)
                    tool_names = json.dumps(sorted(tc.tool for tc in decision.tool_calls))
                    if tool_names == _last_tool_names:
                        _name_repeat_count += 1
                    else:
                        _name_repeat_count = 0
                        _last_tool_names = tool_names

                    is_loop = _repeat_count >= 2 or _name_repeat_count >= 3
                    if is_loop:
                        reason = "exact args" if _repeat_count >= 2 else "same tool"
                        logger.warning(
                            "Loop detected (%s): tool repeated %d times",
                            reason,
                            max(_repeat_count, _name_repeat_count) + 1,
                        )
                        self.context_service.merge_step_result(
                            co, step_number, "loop_detected",
                            "System: repeated tool calls detected ({}). "
                            "Previous calls did not produce useful progress. "
                            "Please try a completely different approach or ask the user for help.".format(reason),
                        )
                        decision.tool_calls = []
                        decision.human_required = True
                        decision.human_reason = "检测到重复工具调用，工具可能未返回有效数据。请选择下一步操作。"
                        decision.options = ["换一种方式继续", "终止"]

                if decision.tool_calls:
                    execution.status = ExecutionStatus.RUNNING_TOOL
                    execution.tool_calls = [tc.model_dump() for tc in decision.tool_calls]
                    self.session.commit()

                    if self._on_step_update:
                        self._on_step_update(execution, "running_tool")

                    all_results = []
                    for tc in decision.tool_calls:
                        if self.tool_service.needs_human_approval(tc.tool):
                            # Ask human to approve tool call
                            execution.status = ExecutionStatus.AWAITING_HUMAN
                            self.session.commit()
                            if self._on_tool_confirm:
                                self._on_tool_confirm(execution, tc)
                            human = await self._wait_for_human()
                            if human["decision"] == "reject":
                                all_results.append({
                                    "tool": tc.tool,
                                    "status": "rejected",
                                    "reason": human.get("text", "User rejected"),
                                })
                                continue
                            execution.status = ExecutionStatus.RUNNING_TOOL
                            self.session.commit()

                        result = await self.tool_service.execute(tc)
                        all_results.append({"tool": tc.tool, **result})

                        # Record artifact if file was written
                        if tc.tool == "file_write" and result.get("status") == "ok":
                            self.artifact_service.record(
                                co_id=co_id,
                                execution_id=execution.id,
                                name=tc.args.get("path", "unknown").split("/")[-1],
                                file_path=result.get("path", tc.args.get("path", "")),
                                artifact_type="document",
                            )
                            self.context_service.add_artifact(co, result.get("path", ""))

                        # Merge tool result into context, including param-filter warnings
                        result_summary = json.dumps(result, ensure_ascii=False)[:2000]
                        removed = _removed_params.get(tc.tool)
                        if removed:
                            result_summary = (
                                f"[WARNING: parameters {removed} are NOT accepted by "
                                f"this tool and were ignored. Only use parameters listed "
                                f"in the tool schema.] {result_summary}"
                            )
                        self.context_service.merge_tool_result(
                            co, step_number, tc.tool, result_summary
                        )

                    execution.tool_results = all_results
                    self.session.commit()

                # 6. Handle human decision request
                if decision.human_required:
                    execution.status = ExecutionStatus.AWAITING_HUMAN
                    self.session.commit()

                    if self._on_human_required:
                        self._on_human_required(
                            execution,
                            decision.human_reason or "Your input is needed.",
                            decision.options,
                        )

                    # Pause CO status
                    self.co_service.update_status(co_id, COStatus.PAUSED)

                    human = await self._wait_for_human()
                    execution.human_decision = human["decision"]
                    execution.human_input = human.get("text", "")
                    execution.status = ExecutionStatus.APPROVED
                    self.session.commit()

                    # Resume CO
                    self.co_service.update_status(co_id, COStatus.RUNNING)

                    if human["decision"].lower() == "abort":
                        execution.status = ExecutionStatus.REJECTED
                        self.session.commit()
                        self.co_service.update_status(co_id, COStatus.ABORTED)
                        await self.tool_service.disconnect()
                        if self._on_complete:
                            self._on_complete(co_id, "aborted")
                        return

                    # Merge human input into context
                    self.context_service.merge_step_result(
                        co, step_number,
                        "human_decision",
                        f"{human['decision']}: {human.get('text', '')}",
                    )

                # 7. Merge step result into context (for non-tool steps)
                if not decision.tool_calls:
                    # Extract a brief summary from LLM response for context
                    summary = response[:300] if response else "No response"
                    self.context_service.merge_step_result(
                        co, step_number, execution.title, summary
                    )

                execution.status = ExecutionStatus.COMPLETED
                self.session.commit()

                # Notify TUI
                if self._on_step_update:
                    self._on_step_update(execution, "completed")

                # 8. Self-evaluation (every N steps)
                cfg = get_config()
                if step_number % cfg.reflection.interval == 0:
                    try:
                        reflection_response = await self.llm_service.reflect(co.context)
                        reflection_decision = self.llm_service.parse_decision(reflection_response)
                        reflection_text = reflection_decision.reflection or reflection_response[:200]
                        self.context_service.merge_reflection(co, reflection_text)
                    except Exception as e:
                        logger.warning("Reflection failed: %s", e)

                # 9. Memory extraction
                self.memory_service.extract_and_save(co_id, response, execution.title)

                # 10. Context compression
                self.context_service.compress_if_needed(co)

                # 11. Check completion
                if decision.task_complete:
                    self.co_service.update_status(co_id, COStatus.COMPLETED)
                    await self.tool_service.disconnect()
                    if self._on_complete:
                        self._on_complete(co_id, "completed")
                    return

        except asyncio.CancelledError:
            logger.info("Execution loop cancelled for CO %s", co_id[:8])
            self.co_service.update_status(co_id, COStatus.PAUSED)
            await self.tool_service.disconnect()
            raise
        except Exception as e:
            logger.error("Execution loop failed for CO %s: %s", co_id[:8], e, exc_info=True)
            self.co_service.update_status(co_id, COStatus.FAILED)
            await self.tool_service.disconnect()
            if self._on_error:
                self._on_error(str(e))
