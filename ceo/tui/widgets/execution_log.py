"""Execution log widget — displays execution steps and LLM responses."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, RichLog

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


class ExecutionLog(Vertical):
    """Displays the execution steps for a CognitiveObject."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._lines: list[str] = []
        self._tool_results: List[Dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        yield Button("Copy", id="exec-log-copy", variant="default")
        yield Button("View Result", id="exec-log-view-result", variant="default")
        yield RichLog(wrap=True, id="exec-log-richlog")

    def on_mount(self) -> None:
        self.border_title = "Execution Log"

    @property
    def _log(self) -> RichLog:
        return self.query_one("#exec-log-richlog", RichLog)

    @staticmethod
    def _strip_markup(text: str) -> str:
        """Remove Rich markup tags for plain-text copy."""
        return re.sub(r"\[/?[^\]]*\]", "", text)

    def _write(self, text: str) -> None:
        """Write a line to both the RichLog and the internal buffer."""
        self._lines.append(text)
        self._log.write(text)

    def clear(self) -> None:
        self._lines.clear()
        self._tool_results.clear()
        self._log.clear()

    def _format_ts(self, ex: Execution) -> str:
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
        self._write(f"{ts}{icon} Step {ex.sequence_number}: {ex.title}")
        if ex.llm_response and ex.status in ("completed", "awaiting_human", "approved"):
            self._write(f"  \u2514\u2500 {ex.llm_response}")
        if ex.tool_results:
            for tr in ex.tool_results:
                status = tr.get("status", "?")
                tool = tr.get("tool", "?")
                self._write(f"  \u2514\u2500 Tool [{tool}]: {status}  [dim](press t to view)[/dim]")
                self._tool_results.append(tr)
        if ex.human_decision:
            self._write(f"  \u2514\u2500 [yellow]\U0001f464 Decision: {ex.human_decision}[/yellow]")
        if ex.human_input:
            self._write(f"  \u2514\u2500 [yellow]\U0001f4ac Feedback: {ex.human_input}[/yellow]")

    def add_step(self, ex: Execution, phase: str = "") -> None:
        """Add or update a single execution step."""
        icon = STATUS_ICONS.get(ex.status, "?")
        ts = self._format_ts(ex)
        if phase == "running_llm":
            self._write(f"{ts}{icon} Step {ex.sequence_number}: Thinking...")
        elif phase == "llm_done":
            self._write(f"{ts}{icon} Step {ex.sequence_number}: {ex.title}")
            if ex.llm_response:
                self._write(f"  \u2514\u2500 {ex.llm_response}")
        elif phase == "running_tool":
            tool_names = ", ".join(
                tc.get("tool", "?") for tc in (ex.tool_calls or [])
            )
            self._write(f"{ts}\U0001f527 Executing tools: {tool_names}")
        elif phase == "completed":
            self._write(f"{ts}\u2713 Step {ex.sequence_number} completed: {ex.title}")
            if ex.tool_results:
                for tr in ex.tool_results:
                    status = tr.get("status", "?")
                    tool = tr.get("tool", "?")
                    self._write(f"  \u2514\u2500 Tool [{tool}]: {status}  [dim](press t to view)[/dim]")
                    self._tool_results.append(tr)
        else:
            self._write_execution(ex)

    def add_error(self, error: str) -> None:
        """Add an error entry to the log."""
        self._write(f"[red bold]\u2717 Error: {error}[/red bold]")

    def show_tool_result_picker(self) -> None:
        """Show tool result detail in a modal."""
        if not self._tool_results:
            self.notify("No tool results to view", severity="warning")
            return
        if len(self._tool_results) == 1:
            result = self._tool_results[0]
            tool_name = result.get("tool", "unknown")
            from ceo.tui.screens.tool_result import ToolResultScreen
            self.app.push_screen(ToolResultScreen(tool_name, result))
        else:
            from ceo.tui.screens.tool_result import ToolResultListScreen, ToolResultScreen

            def on_selected(result: dict | None) -> None:
                if result is not None:
                    tool_name = result.get("tool", "unknown")
                    self.app.push_screen(ToolResultScreen(tool_name, result))

            self.app.push_screen(
                ToolResultListScreen(self._tool_results), callback=on_selected
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "exec-log-copy":
            plain = "\n".join(self._strip_markup(line) for line in self._lines)
            if not plain.strip():
                self.notify("No log content to copy", severity="warning")
                return
            self.app.copy_to_clipboard(plain)
            self.notify("Log copied to clipboard")
        elif event.button.id == "exec-log-view-result":
            self.show_tool_result_picker()
