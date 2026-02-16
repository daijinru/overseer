"""Execution log widget — displays execution steps and LLM responses."""

from __future__ import annotations

from textual.widgets import RichLog

from ceo.models.execution import Execution


STATUS_ICONS = {
    "pending": "\u23f3",
    "running_llm": "\U0001f9e0",
    "running_tool": "\U0001f527",
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
        self.border_title = "Execution Log"

    def _format_ts(self, ex: Execution) -> str:
        """Format the timestamp prefix for an execution step."""
        if ex.created_at:
            return f"[dim]{ex.created_at.strftime('%H:%M:%S')}[/dim] "
        return ""

    def show_executions(self, executions: list[Execution]) -> None:
        """Display all executions for a CO."""
        self.clear()
        for ex in executions:
            self._write_execution(ex)

    def _write_execution(self, ex: Execution) -> None:
        icon = STATUS_ICONS.get(ex.status, "?")
        ts = self._format_ts(ex)
        self.write(f"{ts}{icon} Step {ex.sequence_number}: {ex.title}")
        if ex.llm_response and ex.status in ("completed", "awaiting_human", "approved"):
            self.write(f"  \u2514\u2500 {ex.llm_response}")
        if ex.tool_results:
            for tr in ex.tool_results:
                status = tr.get("status", "?")
                tool = tr.get("tool", "?")
                self.write(f"  \u2514\u2500 Tool [{tool}]: {status}")
        if ex.human_decision:
            self.write(f"  \u2514\u2500 [yellow]\U0001f464 Decision: {ex.human_decision}[/yellow]")
        if ex.human_input:
            self.write(f"  \u2514\u2500 [yellow]\U0001f4ac Feedback: {ex.human_input}[/yellow]")

    def add_step(self, ex: Execution, phase: str = "") -> None:
        """Add or update a single execution step."""
        icon = STATUS_ICONS.get(ex.status, "?")
        ts = self._format_ts(ex)
        if phase == "running_llm":
            self.write(f"{ts}{icon} Step {ex.sequence_number}: Thinking...")
        elif phase == "llm_done":
            self.write(f"{ts}{icon} Step {ex.sequence_number}: {ex.title}")
            if ex.llm_response:
                self.write(f"  \u2514\u2500 {ex.llm_response}")
        elif phase == "running_tool":
            tool_names = ", ".join(
                tc.get("tool", "?") for tc in (ex.tool_calls or [])
            )
            self.write(f"{ts}\U0001f527 Executing tools: {tool_names}")
        elif phase == "completed":
            self.write(f"{ts}\u2713 Step {ex.sequence_number} completed: {ex.title}")
        else:
            self._write_execution(ex)

    def add_error(self, error: str) -> None:
        """Add an error entry to the log."""
        self.write(f"[red bold]\u2717 Error: {error}[/red bold]")
