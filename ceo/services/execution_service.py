"""Execution service — the core orchestration engine (cognitive loop)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

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

# Keywords that indicate the user wants to stop/abort execution.
# Covers both Chinese and English variants used by the UI.
_ABORT_KEYWORDS = frozenset({"abort", "终止", "停止", "取消"})


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

        # Phase 3: User behavior perception state
        # Per-tool approval statistics: {tool_name: {"approve": N, "reject": N}}
        self._approval_stats: Dict[str, Dict[str, int]] = {}
        # Per-tool consecutive reject counter: {tool_name: count}
        self._consecutive_rejects: Dict[str, int] = {}
        # Threshold: consecutive rejects before auto-escalating permission
        self._auto_escalate_threshold = 3
        # Hesitation threshold in seconds — response slower than this injects a signal
        self._hesitation_threshold = 30.0

        # HITL consecutive stop counter — force abort if user repeatedly says "终止"
        self._consecutive_hitl_stops: int = 0

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

    _NO_PROGRESS_INDICATORS = [
        "没有进展", "未取得进展", "停滞", "陷入", "原地踏步",
        "no progress", "stuck", "stagnant", "not making progress",
        "going in circles", "没有推进", "无法推进", "效果不佳",
        "repeated", "重复", "ineffective", "无效",
    ]

    def _detect_no_progress(self, reflection_text: str) -> bool:
        """Check if a reflection indicates lack of progress."""
        text_lower = reflection_text.lower()
        return any(ind in text_lower for ind in self._NO_PROGRESS_INDICATORS)

    # ── Phase 3: User behavior perception helpers ──

    def _record_approval(self, tool_name: str, approved: bool) -> None:
        """Record an approve/reject decision for a tool."""
        if tool_name not in self._approval_stats:
            self._approval_stats[tool_name] = {"approve": 0, "reject": 0}
        key = "approve" if approved else "reject"
        self._approval_stats[tool_name][key] += 1

        if approved:
            self._consecutive_rejects[tool_name] = 0
        else:
            self._consecutive_rejects[tool_name] = (
                self._consecutive_rejects.get(tool_name, 0) + 1
            )

    def _check_auto_escalate(self, tool_name: str, co_id: str) -> None:
        """Auto-escalate permission if user consecutively rejects a tool."""
        count = self._consecutive_rejects.get(tool_name, 0)
        if count >= self._auto_escalate_threshold:
            logger.warning(
                "User rejected '%s' %d consecutive times — escalating permission",
                tool_name, count,
            )
            self.tool_service.override_permission(tool_name, "approve")
            if self._on_info:
                self._on_info(
                    co_id,
                    f"[Perception] Tool '{tool_name}' permission escalated to 'approve' "
                    f"after {count} consecutive rejections",
                )
            # Reset counter after escalation
            self._consecutive_rejects[tool_name] = 0

    def _build_approval_summary(self) -> List[Dict[str, Any]]:
        """Build a summary of implicit user preferences from approval stats."""
        preferences: List[Dict[str, Any]] = []
        for tool, stats in self._approval_stats.items():
            total = stats["approve"] + stats["reject"]
            if total < 2:
                continue  # not enough data
            reject_rate = stats["reject"] / total
            preferences.append({
                "tool": tool,
                "approve": stats["approve"],
                "reject": stats["reject"],
                "reject_rate": round(reject_rate, 2),
            })
        return preferences

    def _persist_preferences(self, co_id: str) -> None:
        """Write stable implicit preferences to Memory for future CO reuse."""
        for tool, stats in self._approval_stats.items():
            total = stats["approve"] + stats["reject"]
            if total < 3:
                continue  # need sufficient data points
            reject_rate = stats["reject"] / total
            if reject_rate >= 0.7:
                content = (
                    f"User tends to reject tool '{tool}' "
                    f"(reject rate {reject_rate:.0%}, n={total}). "
                    f"Consider avoiding this tool or requesting confirmation beforehand."
                )
            elif reject_rate <= 0.1 and total >= 5:
                content = (
                    f"User consistently approves tool '{tool}' "
                    f"(approve rate {1 - reject_rate:.0%}, n={total}). "
                    f"This tool can likely be used with auto permission."
                )
            else:
                continue
            # Avoid duplicate memories — check if similar preference already exists
            existing = self.memory_service.retrieve(f"preference {tool}", limit=1)
            if existing and tool in existing[0].content:
                continue
            self.memory_service.save(
                category="preference",
                content=content,
                tags=["implicit_preference", tool],
                source_co_id=co_id,
            )

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

        # Phase 1: Meta-perception state
        _confidence_history: list[float] = []  # sliding window of recent confidence values
        _low_confidence_window = 3  # how many consecutive low-confidence steps trigger HITL
        _low_confidence_threshold = 0.4  # confidence below this is considered "low"
        _loop_start_time = asyncio.get_event_loop().time()

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
                elapsed = asyncio.get_event_loop().time() - _loop_start_time
                prompt = self.context_service.build_prompt(
                    co, memories, available_tools, elapsed_seconds=elapsed,
                )
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

                # 4.5 Meta-perception: confidence monitoring
                _confidence_history.append(decision.confidence)
                if len(_confidence_history) > _low_confidence_window:
                    _confidence_history = _confidence_history[-_low_confidence_window:]

                # Check for sustained low confidence → auto-trigger HITL
                if (
                    len(_confidence_history) >= _low_confidence_window
                    and all(c < _low_confidence_threshold for c in _confidence_history)
                    and not decision.human_required
                    and not decision.task_complete
                ):
                    avg_conf = sum(_confidence_history) / len(_confidence_history)
                    logger.warning(
                        "Low confidence detected: avg=%.2f over last %d steps",
                        avg_conf, _low_confidence_window,
                    )
                    self.context_service.merge_step_result(
                        co, step_number, "meta_perception",
                        f"System: confidence has been low (avg {avg_conf:.2f}) for "
                        f"{_low_confidence_window} consecutive steps. "
                        f"The current approach may not be effective.",
                    )
                    decision.human_required = True
                    decision.human_reason = (
                        f"系统检测到连续 {_low_confidence_window} 步置信度偏低"
                        f"（平均 {avg_conf:.2f}），当前策略可能无效。请决定下一步方向。"
                    )
                    decision.options = ["换一种方式继续", "提供更多信息", "终止"]
                    _confidence_history.clear()

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

                    # Phase 1: Dynamic loop detection — lower thresholds when confidence is low
                    avg_conf = (
                        sum(_confidence_history) / len(_confidence_history)
                        if _confidence_history else 0.5
                    )
                    # High confidence (>0.7): use default thresholds (2/3)
                    # Low confidence (<0.4): tighten to (1/2)
                    exact_threshold = 2 if avg_conf >= 0.5 else 1
                    name_threshold = 3 if avg_conf >= 0.5 else 2

                    is_loop = _repeat_count >= exact_threshold or _name_repeat_count >= name_threshold
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

                            # Phase 3: Time the approval wait
                            _approval_start = time.monotonic()
                            human = await self._wait_for_human()
                            _approval_elapsed = time.monotonic() - _approval_start

                            is_approved = human["decision"] != "reject"
                            self._record_approval(tc.tool, is_approved)

                            # Phase 3: Hesitation detection
                            if _approval_elapsed >= self._hesitation_threshold:
                                logger.info(
                                    "User hesitated %.1fs on tool '%s' (decision: %s)",
                                    _approval_elapsed, tc.tool, human["decision"],
                                )
                                self.context_service.merge_step_result(
                                    co, step_number, "perception:hesitation",
                                    f"System: user took {_approval_elapsed:.0f}s to respond "
                                    f"to '{tc.tool}' (decision: {human['decision']}). "
                                    f"User may be uncertain about this operation — "
                                    f"consider explaining your intent more clearly next time.",
                                )
                                if self._on_info:
                                    self._on_info(
                                        co_id,
                                        f"[Perception] User hesitated {_approval_elapsed:.0f}s on '{tc.tool}'",
                                    )

                            if not is_approved:
                                all_results.append({
                                    "tool": tc.tool,
                                    "status": "rejected",
                                    "reason": human.get("text", "User rejected"),
                                })
                                # Phase 3: Check if consecutive rejects trigger escalation
                                self._check_auto_escalate(tc.tool, co_id)
                                continue
                            execution.status = ExecutionStatus.RUNNING_TOOL
                            self.session.commit()

                        result = await self.tool_service.execute(tc)
                        all_results.append({"tool": tc.tool, **result})

                        # Record artifact if file was written
                        # Works for both builtin file_write and MCP tools with path args
                        _path_arg = (
                            tc.args.get("path") or tc.args.get("file_path")
                            or tc.args.get("filepath") or tc.args.get("filename")
                            or tc.args.get("outputPath") or tc.args.get("output_path")
                            or tc.args.get("savePath") or tc.args.get("save_path")
                        )
                        if _path_arg and result.get("status") == "ok":
                            self.artifact_service.record(
                                co_id=co_id,
                                execution_id=execution.id,
                                name=_path_arg.split("/")[-1],
                                file_path=result.get("path", _path_arg),
                                artifact_type="document",
                            )
                            self.context_service.add_artifact(co, result.get("path", _path_arg))

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
                            co, step_number, tc.tool, result_summary,
                            raw_result=result,
                        )

                    execution.tool_results = all_results
                    self.session.commit()

                    # Phase 2: Intent-result deviation detection
                    intent_desc = (
                        decision.next_action.description
                        if decision.next_action else ""
                    )
                    deviation = self.context_service.check_intent_deviation(
                        intent_desc, all_results,
                    )
                    if deviation:
                        logger.info("Intent-result deviation: %s", deviation)
                        self.context_service.merge_step_result(
                            co, step_number, "perception:deviation",
                            f"System: {deviation}",
                        )
                        if self._on_info:
                            self._on_info(co_id, f"[Perception] {deviation}")

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

                    # Phase 3: Time the human response
                    _hitl_start = time.monotonic()
                    human = await self._wait_for_human()
                    _hitl_elapsed = time.monotonic() - _hitl_start

                    # Phase 3: Inject hesitation signal for HITL decisions too
                    if _hitl_elapsed >= self._hesitation_threshold:
                        self.context_service.merge_step_result(
                            co, step_number, "perception:hesitation",
                            f"System: user took {_hitl_elapsed:.0f}s to respond to HITL request. "
                            f"User may need more context or is uncertain about the direction.",
                        )

                    execution.human_decision = human["decision"]
                    execution.human_input = human.get("text", "")

                    # Check abort BEFORE setting APPROVED status
                    if human["decision"].lower().strip() in _ABORT_KEYWORDS:
                        self._consecutive_hitl_stops += 1
                        logger.info(
                            "User chose to abort (decision=%r, consecutive=%d)",
                            human["decision"], self._consecutive_hitl_stops,
                        )
                        execution.status = ExecutionStatus.REJECTED
                        self.session.commit()
                        self.co_service.update_status(co_id, COStatus.ABORTED)
                        await self.tool_service.disconnect()
                        if self._on_complete:
                            self._on_complete(co_id, "aborted")
                        return

                    # Non-abort: reset consecutive stop counter
                    self._consecutive_hitl_stops = 0
                    execution.status = ExecutionStatus.APPROVED
                    self.session.commit()

                    # Resume CO
                    self.co_service.update_status(co_id, COStatus.RUNNING)

                    # Detect implicit stop intent in user's free-text feedback
                    _user_text = human.get("text", "").lower()
                    _implicit_stop_cues = (
                        "停", "不要", "别做了", "别继续", "算了",
                        "不用了", "放弃", "stop", "quit", "enough",
                    )
                    _has_implicit_stop = any(kw in _user_text for kw in _implicit_stop_cues)

                    # Merge human input into context (with amplified signal if implicit stop detected)
                    decision_text = f"{human['decision']}: {human.get('text', '')}"
                    if _has_implicit_stop:
                        decision_text += (
                            "\n[System: user's feedback contains stop/abort intent. "
                            "Strongly respect the user's wish — wrap up immediately "
                            "or set task_complete: true.]"
                        )
                    self.context_service.merge_step_result(
                        co, step_number,
                        "human_decision",
                        decision_text,
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

                        # Phase 1: Detect "no progress" signals in reflection
                        _no_progress = self._detect_no_progress(reflection_text)
                        if _no_progress:
                            logger.warning("Reflection indicates no progress: %s", reflection_text[:100])
                            self.context_service.merge_step_result(
                                co, step_number, "meta_perception",
                                "System: self-reflection indicates lack of progress. "
                                "Consider changing your approach entirely — "
                                "use different tools, reframe the problem, "
                                "or ask the user for clarification.",
                            )
                            if self._on_info:
                                self._on_info(co_id, "[Meta] Reflection detected stagnation, strategy switch hint injected")
                    except Exception as e:
                        logger.warning("Reflection failed: %s", e)

                # 9. Memory extraction
                self.memory_service.extract_and_save(co_id, response, execution.title)

                # 9.5 Phase 3: Inject approval stats into context periodically
                if step_number % cfg.reflection.interval == 0:
                    prefs = self._build_approval_summary()
                    if prefs:
                        pref_lines = "; ".join(
                            f"{p['tool']}: {p['approve']} approved, "
                            f"{p['reject']} rejected ({p['reject_rate']:.0%} reject rate)"
                            for p in prefs
                        )
                        self.context_service.merge_step_result(
                            co, step_number, "perception:user_preferences",
                            f"System: implicit user tool preferences — {pref_lines}. "
                            f"Adjust your approach based on these signals.",
                        )

                # 10. Context compression
                self.context_service.compress_if_needed(co)

                # 11. Check completion
                if decision.task_complete:
                    # Phase 3: Persist implicit preferences to Memory before exiting
                    self._persist_preferences(co_id)
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
