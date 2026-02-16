"""Execution log widget — displays execution steps and LLM responses."""

from __future__ import annotations

import platform
import re
import subprocess
from typing import Any, Dict, List

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import RichLog

from ceo.models.execution import Execution

LLM_RESPONSE_MAX = 120
TOOL_PREVIEW_MAX = 80

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


def _copy_to_system_clipboard(text: str) -> bool:
    """Copy text to system clipboard. Returns True on success."""
    try:
        if platform.system() == "Darwin":
            subprocess.run(["pbcopy"], input=text.encode(), check=True)
            return True
        elif platform.system() == "Linux":
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text.encode(), check=True,
            )
            return True
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return False


class ExecutionLog(Vertical):
    """Displays the execution steps for a CognitiveObject."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._lines: list[str] = []
        self._tool_results: List[Dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        yield RichLog(wrap=True, markup=True, id="exec-log-richlog")

    def on_mount(self) -> None:
        self.border_title = "Execution Log"
        self.border_subtitle = "[dim]t[/dim] view  [dim]y[/dim] copy"

    @property
    def _log(self) -> RichLog:
        return self.query_one("#exec-log-richlog", RichLog)

    @staticmethod
    def _strip_markup(text: str) -> str:
        """Remove Rich markup tags for plain-text copy."""
        return re.sub(r"\[/?[^\]]*\]", "", text)

    def _write(self, text: str) -> None:
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

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        text = text.replace("\n", " ").strip()
        if len(text) <= max_len:
            return text
        return text[:max_len] + "\u2026"

    @staticmethod
    def _tool_preview(tr: Dict[str, Any]) -> str:
        """Extract a short preview from tool result output."""
        content = tr.get("output") or tr.get("content") or tr.get("error") or ""
        if not content:
            return ""
        preview = content.replace("\n", " ").strip()
        if len(preview) > TOOL_PREVIEW_MAX:
            preview = preview[:TOOL_PREVIEW_MAX] + "\u2026"
        return preview

    def _write_separator(self) -> None:
        self._write("")
        self._write("[dim]\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500[/dim]")
        self._write("")

    def show_executions(self, executions: list[Execution]) -> None:
        """Display all executions for a CO."""
        self.clear()
        for i, ex in enumerate(executions):
            if i > 0:
                self._write_separator()
            self._write_execution(ex)

    def _write_execution(self, ex: Execution) -> None:
        icon = STATUS_ICONS.get(ex.status, "?")
        ts = self._format_ts(ex)
        self._write(f"{ts}{icon} [bold]Step {ex.sequence_number}: {ex.title}[/bold]")
        if ex.llm_response and ex.status in ("completed", "awaiting_human", "approved"):
            summary = self._truncate(ex.llm_response, LLM_RESPONSE_MAX)
            self._write(f"    [italic]{summary}[/italic]")
        if ex.tool_results:
            for tr in ex.tool_results:
                self._write_tool_result(tr)
        if ex.human_decision:
            self._write(f"    [yellow]\U0001f464 Decision: {ex.human_decision}[/yellow]")
        if ex.human_input:
            self._write(f"    [yellow]\U0001f4ac Feedback: {ex.human_input}[/yellow]")

    def _write_tool_result(self, tr: Dict[str, Any]) -> None:
        status = tr.get("status", "?")
        tool = tr.get("tool", "?")
        status_color = "green" if status == "ok" else "red" if status == "error" else "yellow"
        self._write(f"    \u2514 [bold]{tool}[/bold] [{status_color}]{status}[/{status_color}]")
        preview = self._tool_preview(tr)
        if preview:
            self._write(f"      [italic $text-muted]{preview}[/italic $text-muted]")
        self._tool_results.append(tr)

    def add_step(self, ex: Execution, phase: str = "") -> None:
        """Add or update a single execution step."""
        icon = STATUS_ICONS.get(ex.status, "?")
        ts = self._format_ts(ex)
        if phase == "running_llm":
            self._write_separator()
            self._write(f"{ts}{icon} [bold]Step {ex.sequence_number}: Thinking...[/bold]")
        elif phase == "llm_done":
            self._write(f"{ts}{icon} [bold]Step {ex.sequence_number}: {ex.title}[/bold]")
            if ex.llm_response:
                summary = self._truncate(ex.llm_response, LLM_RESPONSE_MAX)
                self._write(f"    [italic]{summary}[/italic]")
        elif phase == "running_tool":
            tool_names = ", ".join(
                tc.get("tool", "?") for tc in (ex.tool_calls or [])
            )
            self._write(f"{ts}\U0001f527 Executing: [bold]{tool_names}[/bold]")
        elif phase == "completed":
            self._write(f"{ts}\u2713 [bold]Step {ex.sequence_number} completed: {ex.title}[/bold]")
            if ex.tool_results:
                for tr in ex.tool_results:
                    self._write_tool_result(tr)
        else:
            self._write_execution(ex)

    def add_info(self, text: str) -> None:
        """Add an informational entry to the log (e.g. MCP server messages)."""
        self._write(f"[dim]\u2139 {text}[/dim]")

    def add_error(self, error: str) -> None:
        """Add an error entry to the log."""
        self._write(f"[red bold]\u2717 Error: {error}[/red bold]")

    def copy_log(self) -> None:
        """Copy all log content to system clipboard."""
        plain = "\n".join(self._strip_markup(line) for line in self._lines)
        if not plain.strip():
            self.notify("No log content to copy", severity="warning")
            return
        if _copy_to_system_clipboard(plain):
            self.notify("Log copied to clipboard")
        else:
            self.app.copy_to_clipboard(plain)
            self.notify("Log copied to clipboard (OSC 52)")

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
