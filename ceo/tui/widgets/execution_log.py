"""Execution log widget — displays execution steps and LLM responses."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import RichLog

from ceo.models.execution import Execution


STATUS_ICONS = {
    "pending": "\u23f3",
    "running_llm": "\ud83e\udde0",
    "running_tool": "\ud83d\udd27",
    "awaiting_human": "\u270b",
    "approved": "\u2705",
    "rejected": "\u274c",
    "completed": "\u2713",
    "failed": "\u2717",
}


class ExecutionLog(RichLog):
    """Displays the execution steps for a CognitiveObject."""

    def __init__(self, **kwargs) -> None:
        super().__init__(wrap=True, **kwargs)

    def show_executions(self, executions: list[Execution]) -> None:
        """Display all executions for a CO."""
        self.clear()
        for ex in executions:
            self._write_execution(ex)

    def _write_execution(self, ex: Execution) -> None:
        icon = STATUS_ICONS.get(ex.status, "?")
        self.write(f"{icon} Step {ex.sequence_number}: {ex.title}")
        if ex.llm_response and ex.status in ("completed", "awaiting_human", "approved"):
            self.write(f"  \u2514\u2500 {ex.llm_response}")
        if ex.tool_results:
            for tr in ex.tool_results:
                status = tr.get("status", "?")
                tool = tr.get("tool", "?")
                self.write(f"  \u2514\u2500 Tool [{tool}]: {status}")

    def add_step(self, ex: Execution, phase: str = "") -> None:
        """Add or update a single execution step."""
        icon = STATUS_ICONS.get(ex.status, "?")
        if phase == "running_llm":
            self.write(f"{icon} Step {ex.sequence_number}: Thinking...")
        elif phase == "llm_done":
            self.write(f"{icon} Step {ex.sequence_number}: {ex.title}")
            if ex.llm_response:
                self.write(f"  \u2514\u2500 {ex.llm_response}")
        elif phase == "running_tool":
            tool_names = ", ".join(
                tc.get("tool", "?") for tc in (ex.tool_calls or [])
            )
            self.write(f"\ud83d\udd27 Executing tools: {tool_names}")
        elif phase == "completed":
            self.write(f"\u2713 Step {ex.sequence_number} completed: {ex.title}")
        else:
            self._write_execution(ex)
