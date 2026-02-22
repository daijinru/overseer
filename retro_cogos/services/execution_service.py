"""Execution service — the core orchestration engine (cognitive loop)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from retro_cogos.core.enums import COStatus, ExecutionStatus
from retro_cogos.core.protocols import LLMDecision, Subtask, ToolCall
from retro_cogos.database import get_session
from retro_cogos.models.cognitive_object import CognitiveObject
from retro_cogos.models.execution import Execution
from retro_cogos.services.artifact_service import ArtifactService
from retro_cogos.services.cognitive_object_service import CognitiveObjectService
from retro_cogos.services.context_service import ContextService
from retro_cogos.services.llm_service import LLMService
from retro_cogos.services.memory_service import MemoryService
from retro_cogos.services.planning_service import PlanningService
from retro_cogos.services.tool_service import ToolService
from retro_cogos.config import get_config

logger = logging.getLogger(__name__)

# Keywords that indicate the user wants to stop/abort execution.
# Covers both Chinese and English variants used by the UI.
_ABORT_KEYWORDS = frozenset({
    # English
    "abort", "stop", "quit", "exit", "end", "cancel", "finish",
    "done", "enough", "terminate",
    # Chinese
    "终止", "停止", "取消", "结束", "退出", "关闭",
    "不做了", "不用了", "不要了", "不需要了",
    "算了", "放弃", "中止", "停下", "别做了",
})


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
        self.planning_service = PlanningService(self.llm_service, self.context_service)

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
            # Inject avoidance hint so LLM stops calling this tool
            co = self.co_service.get(co_id)
            if co:
                self.context_service.merge_step_result(
                    co,
                    (co.context or {}).get("step_count", 0),
                    "perception:tool_avoidance",
                    f"System: user has rejected tool '{tool_name}' {count} consecutive times. "
                    f"STOP using this tool. Find an alternative approach or ask for guidance.",
                )
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

    # ── Cognitive scaffold: planning, checkpoint, compression ──

    async def _run_planning_phase(self, co_id: str) -> bool:
        """Phase 1: Generate a task plan via LLM.

        Returns True if a plan was generated, False otherwise.
        """
        co = self.co_service.get(co_id)
        if co is None:
            return False

        if self._on_info:
            self._on_info(co_id, "[Phase] Entering planning phase...")

        memories = self.memory_service.retrieve_as_text(
            co.title + " " + co.description, limit=3
        )
        available_tools = self.tool_service.list_tools()

        try:
            plan = await self.planning_service.generate_plan(co, memories, available_tools)
            if plan and plan.subtasks:
                self.planning_service.store_plan(co, plan)
                subtask_titles = [st.title for st in plan.subtasks]
                if self._on_info:
                    self._on_info(
                        co_id,
                        f"[Phase] Planning complete: {len(plan.subtasks)} subtasks — "
                        + ", ".join(subtask_titles),
                    )
                return True
        except Exception as e:
            logger.warning("Planning phase failed, falling back to flat execution: %s", e)

        if self._on_info:
            self._on_info(co_id, "[Phase] Planning skipped, using flat execution mode")
        return False

    async def _run_checkpoint(self, co_id: str) -> None:
        """Phase 3: At subtask boundary, reflect on progress and optionally revise plan."""
        co = self.co_service.get(co_id)
        if co is None:
            return

        if self._on_info:
            self._on_info(co_id, "[Phase] Checkpoint: reviewing progress...")

        revised = await self.planning_service.checkpoint_reflect(co)
        if revised:
            if self._on_info:
                self._on_info(co_id, "[Phase] Plan revised at checkpoint")
        else:
            progress = self.planning_service.get_plan_progress_text(co)
            if self._on_info and progress:
                self._on_info(co_id, f"[Phase] {progress}")

    async def _compress_working_memory(self, co_id: str) -> None:
        """Compress accumulated findings into WorkingMemory at subtask boundary."""
        co = self.co_service.get(co_id)
        if co is None:
            return

        wm = await self.context_service.compress_to_working_memory(co, self.llm_service)
        if wm:
            if self._on_info:
                self._on_info(co_id, "[Phase] Context compressed to working memory")
        else:
            # Fallback to truncation-based compression
            self.context_service.compress_if_needed(co)

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

        cfg = get_config()

        # ── PLANNING PHASE ──
        # Generate a task plan if planning is enabled and no plan exists yet
        if cfg.planning.enabled and not (co.context or {}).get("plan"):
            await self._run_planning_phase(co_id)
            co = self.co_service.get(co_id)  # refresh after planning

        # Track which subtask we announced to avoid duplicate notifications
        _announced_subtask_id = None

        try:
            while True:
                step_number += 1
                co = self.co_service.get(co_id)  # refresh

                # Announce current subtask if changed
                current_subtask = self.planning_service.get_current_subtask(co)
                if current_subtask and current_subtask.id != _announced_subtask_id:
                    _announced_subtask_id = current_subtask.id
                    plan = (co.context or {}).get("plan", {})
                    total = len(plan.get("subtasks", []))
                    if self._on_info:
                        self._on_info(
                            co_id,
                            f"[Phase] Starting subtask {current_subtask.id}/{total}: {current_subtask.title}",
                        )

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

                # 4.6 Help request: explicit escalation protocol
                if decision.help_request and not decision.human_required:
                    hr = decision.help_request
                    decision.human_required = True
                    parts = []
                    if hr.specific_question:
                        parts.append(f"问题：{hr.specific_question}")
                    if hr.attempted_approaches:
                        parts.append(f"已尝试：{', '.join(hr.attempted_approaches)}")
                    if hr.missing_information:
                        parts.append(f"缺少信息：{', '.join(hr.missing_information)}")
                    decision.human_reason = "\n".join(parts) if parts else "需要帮助以继续推进。"
                    decision.options = (hr.suggested_human_actions or []) + ["跳过此步骤", "终止"]

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
                    # High confidence (>=0.5): use default thresholds (2/3)
                    # Low confidence (<0.5): tighten to (1/2)
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
                            tool_args=tc.args,
                        )

                    execution.tool_results = all_results
                    self.session.commit()

                    # Log tool results to file
                    from retro_cogos.logging_config import log_tool_result
                    for tr in all_results:
                        log_tool_result(tr, co_id=co_id, step_number=step_number)

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
                        if self._on_info:
                            self._on_info(
                                co_id,
                                f"[Perception] User hesitated {_hitl_elapsed:.0f}s on HITL decision",
                            )

                    execution.human_decision = human["decision"]
                    execution.human_input = human.get("text", "")

                    # Check abort BEFORE setting APPROVED status.
                    # Match abort keywords in both the button label (decision)
                    # AND the typed free-text — users may type "结束" in the
                    # feedback input rather than clicking a button.
                    _decision_val = human["decision"].lower().strip()
                    _text_val = human.get("text", "").lower().strip()
                    _is_abort = (
                        _decision_val in _ABORT_KEYWORDS
                        or (_decision_val == "feedback" and _text_val in _ABORT_KEYWORDS)
                    )
                    if _is_abort:
                        self._consecutive_hitl_stops += 1
                        logger.info(
                            "User chose to abort (decision=%r, text=%r, consecutive=%d)",
                            human["decision"], human.get("text", ""),
                            self._consecutive_hitl_stops,
                        )

                        # Force-abort only after repeated stop signals (user insists)
                        if self._consecutive_hitl_stops >= 2:
                            logger.info("User insisted on abort (%d times), force-aborting", self._consecutive_hitl_stops)
                            execution.status = ExecutionStatus.REJECTED
                            self.session.commit()
                            self._persist_preferences(co_id)
                            self.co_service.update_status(co_id, COStatus.ABORTED)
                            await self.tool_service.disconnect()
                            if self._on_complete:
                                self._on_complete(co_id, "aborted")
                            return

                        # Graceful abort: inject a strong system signal and let LLM
                        # wrap up in the next iteration instead of hard-aborting.
                        execution.status = ExecutionStatus.APPROVED
                        self.session.commit()
                        self.co_service.update_status(co_id, COStatus.RUNNING)
                        self.context_service.merge_step_result(
                            co, step_number, "system:user_stop_request",
                            "[URGENT — User wants to STOP] "
                            "The user has requested to end this task. "
                            "You MUST do the following in your NEXT response:\n"
                            "1. Provide a brief summary of what has been accomplished so far.\n"
                            "2. Set task_complete: true in your decision.\n"
                            "3. Do NOT start any new work or tool calls.\n"
                            "4. Do NOT ask for confirmation — just finish.",
                        )
                        if self._on_info:
                            self._on_info(
                                co_id,
                                "[System] User requested stop — guiding LLM to wrap up gracefully",
                            )
                        continue

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
                        "不用了", "放弃", "结束", "不做了", "退出",
                        "不需要", "关闭", "中止", "停下", "到此为止",
                        "就这样", "可以了", "够了",
                        "stop", "quit", "enough", "end", "done",
                        "finish", "cancel", "exit", "terminate",
                    )
                    _has_implicit_stop = any(kw in _user_text for kw in _implicit_stop_cues)

                    # Merge human input into context (with amplified signal if implicit stop detected)
                    # When decision is "feedback", the user typed free-text and hit Enter
                    # — use the text itself as the primary intent, not an arbitrary button label.
                    if human["decision"] == "feedback":
                        decision_text = human.get("text", "")
                    else:
                        decision_text = f"{human['decision']}: {human.get('text', '')}"
                    # Detect task-completion confirmation from user.
                    # Check both the button label and typed free-text.
                    _CONFIRM_COMPLETE_KEYWORDS = frozenset({
                        "确认完成", "确认", "完成", "可以了", "没问题",
                        "confirm", "done", "lgtm",
                    })
                    _decision_lower = human["decision"].lower().strip()
                    _feedback_text_lower = human.get("text", "").lower().strip()
                    if (
                        _decision_lower in _CONFIRM_COMPLETE_KEYWORDS
                        or (_decision_lower == "feedback" and _feedback_text_lower in _CONFIRM_COMPLETE_KEYWORDS)
                    ):
                        decision_text += (
                            "\n[System: user has reviewed the summary report and "
                            "confirmed task completion. You MUST set task_complete: true "
                            "in your next decision. Do NOT ask for confirmation again.]"
                        )
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

                # 10. Context compression (truncation fallback — always runs)
                self.context_service.compress_if_needed(co)

                # 10.5 Subtask completion handling
                if decision.subtask_complete and cfg.planning.enabled:
                    current_st = self.planning_service.get_current_subtask(co)
                    result_summary = decision.reflection or ""
                    next_st = self.planning_service.advance_subtask(co, result_summary)

                    if current_st and self._on_info:
                        self._on_info(
                            co_id,
                            f"[Phase] Subtask '{current_st.title}' completed",
                        )

                    # Checkpoint reflection at subtask boundary
                    if cfg.planning.checkpoint_on_subtask_complete:
                        await self._run_checkpoint(co_id)

                    # LLM-based context compression at subtask boundary
                    if cfg.planning.compress_after_subtask:
                        await self._compress_working_memory(co_id)

                    # Reset loop detection counters for new subtask
                    _last_tool_sig = None
                    _repeat_count = 0
                    _last_tool_names = None
                    _name_repeat_count = 0

                    # Check if all subtasks are done
                    co = self.co_service.get(co_id)  # refresh
                    if self.planning_service.all_subtasks_done(co):
                        if self._on_info:
                            self._on_info(co_id, "[Phase] All subtasks completed")

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
            try:
                self._persist_preferences(co_id)
            except Exception:
                logger.debug("Failed to persist preferences on cancel", exc_info=True)
            self.co_service.update_status(co_id, COStatus.PAUSED)
            await self.tool_service.disconnect()
            raise
        except Exception as e:
            logger.error("Execution loop failed for CO %s: %s", co_id[:8], e, exc_info=True)
            try:
                self._persist_preferences(co_id)
            except Exception:
                logger.debug("Failed to persist preferences on error exit", exc_info=True)
            self.co_service.update_status(co_id, COStatus.FAILED)
            await self.tool_service.disconnect()
            if self._on_error:
                self._on_error(str(e))
