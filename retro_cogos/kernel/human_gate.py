"""HumanGate — the sole human-machine communication channel.

When FirewallEngine decides a human must be involved, HumanGate is the
only way to ask and listen. It handles:
- Request / wait / receive (asyncio.Event-based)
- Intent parsing (approve, reject, abort, confirm-complete, freetext)
- Multi-stage abort (first gentle, then forced)
- Hesitation is recorded by the orchestrator into PerceptionBus.

HumanGate does NOT decide *whether* to ask — that's FirewallEngine's job.

Extracted from:
- ExecutionService._wait_for_human / provide_human_response
- ExecutionService.run_loop abort detection (lines 944-994)
- ExecutionService.run_loop intent parsing (lines 1004-1050)
- _ABORT_KEYWORDS constant
"""

from __future__ import annotations

import asyncio
import logging
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Intent enum ──

class Intent(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    ABORT = "abort"
    FORCE_ABORT = "force_abort"
    CONFIRM_COMPLETE = "confirm_complete"
    IMPLICIT_STOP = "implicit_stop"
    FREETEXT = "freetext"


# ── Result types ──

class ApprovalResult:
    """Result of a human approval request."""
    __slots__ = ("approved", "text", "elapsed", "raw_decision")

    def __init__(self, approved: bool, text: str = "", elapsed: float = 0.0,
                 raw_decision: str = "") -> None:
        self.approved = approved
        self.text = text
        self.elapsed = elapsed
        self.raw_decision = raw_decision


class HumanResponse:
    """Result of a human decision request (HITL)."""
    __slots__ = ("intent", "decision", "text", "decision_text", "elapsed")

    def __init__(self, intent: Intent, decision: str, text: str = "",
                 decision_text: str = "", elapsed: float = 0.0) -> None:
        self.intent = intent
        self.decision = decision
        self.text = text
        self.decision_text = decision_text
        self.elapsed = elapsed


# ── Keyword sets for intent detection ──

_ABORT_KEYWORDS = frozenset({
    # English
    "abort", "stop", "quit", "exit", "end", "cancel", "finish",
    "done", "enough", "terminate",
    # Chinese
    "终止", "停止", "取消", "结束", "退出", "关闭",
    "不做了", "不用了", "不要了", "不需要了",
    "算了", "放弃", "中止", "停下", "别做了",
})

_CONFIRM_COMPLETE_KEYWORDS = frozenset({
    "确认完成", "确认", "完成", "可以了", "没问题",
    "confirm", "done", "lgtm",
})

_IMPLICIT_STOP_CUES = (
    "停", "不要", "别做了", "别继续", "算了",
    "不用了", "放弃", "结束", "不做了", "退出",
    "不需要", "关闭", "中止", "停下", "到此为止",
    "就这样", "可以了", "够了",
    "stop", "quit", "enough", "end", "done",
    "finish", "cancel", "exit", "terminate",
)


class HumanGate:
    """The sole human-machine communication channel.

    Manages the asyncio.Event-based request/wait/receive pattern and
    parses user intent from their responses.
    """

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._response: Optional[Dict[str, Any]] = None
        self._consecutive_stops: int = 0

    @property
    def consecutive_stops(self) -> int:
        return self._consecutive_stops

    def reset_consecutive_stops(self) -> None:
        self._consecutive_stops = 0

    # ── TUI → Engine bridge ──

    def provide_response(self, decision: str, text: str = "") -> None:
        """Called by TUI when user makes a decision.

        Extracted from ExecutionService.provide_human_response().
        """
        self._response = {"decision": decision, "text": text}
        self._event.set()

    async def wait_for_human(self) -> Dict[str, Any]:
        """Block until the human provides a response.

        Extracted from ExecutionService._wait_for_human().
        """
        self._event.clear()
        self._response = None
        await self._event.wait()
        return self._response or {"decision": "timeout", "text": ""}

    # ── Intent parsing ──

    def parse_intent(self, human: Dict[str, Any]) -> Intent:
        """Determine user intent from their response.

        Handles abort detection, task-completion confirmation, and
        implicit stop cues in free-text.

        Extracted from ExecutionService.run_loop lines 944-1050.
        """
        decision_val = human.get("decision", "").lower().strip()
        text_val = human.get("text", "").lower().strip()

        # Check abort intent
        is_abort = (
            decision_val in _ABORT_KEYWORDS
            or (decision_val == "feedback" and text_val in _ABORT_KEYWORDS)
        )
        if is_abort:
            self._consecutive_stops += 1
            logger.info(
                "User chose to abort (decision=%r, text=%r, consecutive=%d)",
                human.get("decision", ""), human.get("text", ""),
                self._consecutive_stops,
            )
            if self._consecutive_stops >= 2:
                return Intent.FORCE_ABORT
            return Intent.ABORT

        # Non-abort: reset counter
        self._consecutive_stops = 0

        # Check task-completion confirmation
        if (
            decision_val in _CONFIRM_COMPLETE_KEYWORDS
            or (decision_val == "feedback" and text_val in _CONFIRM_COMPLETE_KEYWORDS)
        ):
            return Intent.CONFIRM_COMPLETE

        # Check implicit stop cues in free-text
        user_text = human.get("text", "").lower()
        if any(kw in user_text for kw in _IMPLICIT_STOP_CUES):
            return Intent.IMPLICIT_STOP

        return Intent.FREETEXT

    def build_decision_text(self, human: Dict[str, Any], intent: Intent) -> str:
        """Build the context-injection text from a human response + parsed intent.

        Extracted from ExecutionService.run_loop lines 1016-1050.
        """
        # Primary text
        if human.get("decision") == "feedback":
            decision_text = human.get("text", "")
        else:
            decision_text = f"{human['decision']}: {human.get('text', '')}"

        # Augment with system signals
        if intent == Intent.CONFIRM_COMPLETE:
            decision_text += (
                "\n[System: user has reviewed the summary report and "
                "confirmed task completion. You MUST set task_complete: true "
                "in your next decision. Do NOT ask for confirmation again.]"
            )
        if intent == Intent.IMPLICIT_STOP:
            decision_text += (
                "\n[System: user's feedback contains stop/abort intent. "
                "Strongly respect the user's wish — wrap up immediately "
                "or set task_complete: true.]"
            )

        return decision_text

    # ── State for checkpoint/restore ──

    def get_state(self) -> Dict[str, Any]:
        """Serialise state for checkpointing."""
        return {"consecutive_stops": self._consecutive_stops}

    def restore_state(self, state: Dict[str, Any]) -> None:
        """Restore state from checkpoint."""
        self._consecutive_stops = state.get("consecutive_stops", 0)
