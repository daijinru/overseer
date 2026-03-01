"""Execution log widget — displays execution steps and LLM responses."""

from __future__ import annotations

import platform
import re
import subprocess
from typing import Any, Dict

from rich.markup import escape as escape_markup
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import RichLog

from overseer.models.execution import Execution

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
        self._last_summary_text: str = ""
        self._stream_buffer: str = ""
        self._stream_lines: list[str] = []

    def compose(self) -> ComposeResult:
        yield RichLog(wrap=True, markup=True, id="exec-log-richlog")

    def on_mount(self) -> None:
        self.border_title = "Execution Log"
        self.border_subtitle = "[dim]y[/dim] copy"

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
        self._last_summary_text = ""
        self._stream_buffer = ""
        self._stream_lines.clear()
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
        self._write(f"{ts}{icon} [bold]Step {ex.sequence_number}: {escape_markup(ex.title or '')}[/bold]")
        # Show token usage if available
        if ex.token_usage:
            tokens = ex.token_usage.get("total_tokens", 0)
            model = ex.token_usage.get("model", "")
            if tokens > 0:
                self._write(f"    [dim]Tokens: {tokens:,}  Model: {model}[/dim]")
        if ex.llm_response and ex.status in ("completed", "awaiting_human", "approved"):
            summary = self._truncate(ex.llm_response, LLM_RESPONSE_MAX)
            self._write(f"    [italic]{escape_markup(summary)}[/italic]")
        if ex.tool_results:
            for tr in ex.tool_results:
                self._write_tool_result(tr)
        if ex.human_decision:
            self._write(f"    [bold italic]\U0001f464 Decision: {escape_markup(ex.human_decision)}[/bold italic]")
        if ex.human_input:
            self._write(f"    [bold italic]\U0001f4ac Feedback: {escape_markup(ex.human_input)}[/bold italic]")

    def _write_tool_result(self, tr: Dict[str, Any]) -> None:
        status = tr.get("status", "?")
        tool = tr.get("tool", "?")
        if status == "ok":
            status_color = "bold"
        elif status == "rejected":
            status_color = "bold reverse"
        elif status == "error":
            status_color = "bold reverse"
        else:
            status_color = "bold italic"
        self._write(f"    \u2514 [bold]{escape_markup(tool)}[/bold] [{status_color}]{escape_markup(status)}[/{status_color}]")
        # Show rejection reason if present
        if status == "rejected":
            reason = tr.get("reason", "")
            if reason:
                self._write(f"      [italic reverse]{escape_markup(reason)}[/italic reverse]")
        else:
            preview = self._tool_preview(tr)
            if preview:
                self._write(f"      [dim italic]{escape_markup(preview)}[/dim italic]")

    def add_step(self, ex: Execution, phase: str = "") -> None:
        """Add or update a single execution step."""
        icon = STATUS_ICONS.get(ex.status, "?")
        ts = self._format_ts(ex)
        if phase == "running_llm":
            self._write_separator()
            self._write(f"{ts}{icon} [bold]Step {ex.sequence_number}: Thinking...[/bold]")
        elif phase == "llm_done":
            self.flush_stream()
            self._write(f"{ts}{icon} [bold]Step {ex.sequence_number}: {escape_markup(ex.title or '')}[/bold]")
            if ex.llm_response:
                summary = self._truncate(ex.llm_response, LLM_RESPONSE_MAX)
                self._write(f"    [italic]{escape_markup(summary)}[/italic]")
        elif phase == "running_tool":
            tool_names = ", ".join(
                tc.get("tool", "?") for tc in (ex.tool_calls or [])
            )
            self._write(f"{ts}\U0001f527 Executing: [bold]{escape_markup(tool_names)}[/bold]")
        elif phase == "completed":
            self._write(f"{ts}\u2713 [bold]Step {ex.sequence_number} completed: {escape_markup(ex.title or '')}[/bold]")
            if ex.tool_results:
                for tr in ex.tool_results:
                    self._write_tool_result(tr)
        else:
            self._write_execution(ex)

    def add_info(self, text: str) -> None:
        """Add an informational entry to the log (e.g. MCP server messages)."""
        self._write(f"[dim]\u2139 {escape_markup(text)}[/dim]")

    def append_stream_chunk(self, text: str) -> None:
        """Append a streaming chunk, line-buffered for proper display."""
        try:
            self._stream_buffer += text
            while "\n" in self._stream_buffer:
                line, self._stream_buffer = self._stream_buffer.split("\n", 1)
                escaped = escape_markup(line) if line else ""
                self._stream_lines.append(escaped)
                self._log.write(escaped, scroll_end=True)
        except Exception:
            pass

    def flush_stream(self) -> None:
        """Flush remaining stream buffer and record all streamed lines for clipboard."""
        if self._stream_buffer:
            escaped = escape_markup(self._stream_buffer)
            self._stream_lines.append(escaped)
            self._log.write(escaped, scroll_end=True)
            self._stream_buffer = ""
        if self._stream_lines:
            self._lines.extend(self._stream_lines)
            self._stream_lines.clear()

    def add_error(self, error: str) -> None:
        """Add an error entry to the log."""
        self._write(f"[bold reverse]\u2717 Error: {escape_markup(error)}[/bold reverse]")

    def add_human_decision(self, choice: str, text: str = "") -> None:
        """Add a user's HITL form decision to the log."""
        if choice == "feedback":
            # User submitted free-text only — show feedback as the decision
            self._write(f"    [bold italic]\U0001f4ac Feedback: {escape_markup(text)}[/bold italic]")
        else:
            self._write(f"    [bold italic]\U0001f464 Decision: {escape_markup(choice)}[/bold italic]")
            if text:
                self._write(f"    [bold italic]\U0001f4ac Feedback: {escape_markup(text)}[/bold italic]")

    def add_tool_approval(self, approved: bool, reason: str = "") -> None:
        """Add a user's tool approval/rejection to the log."""
        if approved:
            self._write("    [bold]\u2705 Tool approved[/bold]")
        else:
            label = f"Tool rejected: {escape_markup(reason)}" if reason else "Tool rejected"
            self._write(f"    [bold reverse]\u274c {label}[/bold reverse]")

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

    def add_completion_summary(self, co) -> None:
        """Append a rich completion summary block to the log."""
        ctx = co.context or {}
        goal = ctx.get("goal", co.title)
        step_count = ctx.get("step_count", 0)
        findings = ctx.get("accumulated_findings", [])
        last_reflection = ctx.get("last_reflection")
        duration = self._calc_duration(co)

        lines: list[str] = []

        lines.append("")
        lines.append("[bold]\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550[/bold]")
        lines.append("[bold]  \u2713 TASK COMPLETED[/bold]")
        lines.append("[bold]\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550[/bold]")
        lines.append("")

        lines.append(f"[bold]Goal:[/bold] {escape_markup(goal)}")
        lines.append("")

        lines.append(f"[bold]Steps:[/bold] {step_count}  |  [bold]Duration:[/bold] {duration}")

        # Token usage summary
        total_tokens = 0
        if hasattr(co, 'executions') and co.executions:
            for ex in co.executions:
                if ex.token_usage:
                    total_tokens += ex.token_usage.get("total_tokens", 0)
        if total_tokens > 0:
            cost = total_tokens / 1_000_000 * 2.0
            lines.append(f"[bold]Tokens:[/bold] {total_tokens:,}  |  [bold]Est. Cost:[/bold] ${cost:.4f}")

        lines.append("")

        if findings:
            _SKIP_KEYS = frozenset({
                "perception:", "meta_perception", "loop_detected",
                "compressed_summary",
            })
            user_findings = [
                f for f in findings
                if not any(f.get("key", "").startswith(sk) for sk in _SKIP_KEYS)
            ]
            if user_findings:
                lines.append("[bold]Key Findings:[/bold]")
                for f in user_findings[-5:]:
                    step = f.get("step", "?")
                    key = f.get("key", "")
                    value = f.get("value", "")
                    if len(value) > 120:
                        value = value[:120] + "\u2026"
                    lines.append(f"  \u2514 Step {step} \\[{escape_markup(key)}]: {escape_markup(value)}")
                if len(user_findings) > 5:
                    lines.append(f"  [dim]\u2026 and {len(user_findings) - 5} earlier findings[/dim]")
                lines.append("")

        artifacts = list(co.artifacts) if co.artifacts else []
        if artifacts:
            lines.append(f"[bold]Artifacts Produced ({len(artifacts)}):[/bold]")
            for art in artifacts:
                type_badge = f"[dim]({escape_markup(art.artifact_type)})[/dim]" if art.artifact_type else ""
                lines.append(f"  \u2514\u2500 {escape_markup(art.name)} {type_badge}")
                lines.append(f"     [dim]{escape_markup(art.file_path)}[/dim]")
            lines.append("")

        if last_reflection:
            lines.append("[bold]Final Reflection:[/bold]")
            refl = last_reflection if len(last_reflection) <= 200 else last_reflection[:200] + "\u2026"
            lines.append(f"  [italic]{escape_markup(refl)}[/italic]")
            lines.append("")

        lines.append("[dim]\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550[/dim]")

        for line in lines:
            self._write(line)

        self._last_summary_text = "\n".join(
            self._strip_markup(line) for line in lines
        )

    def copy_summary(self) -> None:
        """Copy the completion summary text to system clipboard."""
        if not self._last_summary_text:
            self.notify("No summary to copy", severity="warning")
            return
        if _copy_to_system_clipboard(self._last_summary_text):
            self.notify("Summary copied to clipboard")
        else:
            self.app.copy_to_clipboard(self._last_summary_text)
            self.notify("Summary copied to clipboard (OSC 52)")

    @staticmethod
    def _calc_duration(co) -> str:
        """Calculate duration string for a CO."""
        from datetime import datetime, timezone
        if not co.created_at:
            return "-"
        end = co.updated_at if co.updated_at else co.created_at
        delta = end - co.created_at
        total_seconds = int(delta.total_seconds())
        if total_seconds < 0:
            return "-"
        if total_seconds < 60:
            return f"{total_seconds}s"
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        if minutes < 60:
            return f"{minutes}m {seconds}s"
        hours = minutes // 60
        minutes = minutes % 60
        return f"{hours}h {minutes}m"
