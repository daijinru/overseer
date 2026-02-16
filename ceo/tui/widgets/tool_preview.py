"""Tool preview panel — shows tool call details for human approval."""

from __future__ import annotations

import json

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, Input, Static

from ceo.core.protocols import ToolCall


class ToolPreview(Static):
    """Panel for previewing and approving/rejecting tool calls."""

    class Approved(Message):
        def __init__(self) -> None:
            super().__init__()

    class Rejected(Message):
        def __init__(self, reason: str = "") -> None:
            super().__init__()
            self.reason = reason

    def compose(self) -> ComposeResult:
        yield Static("", id="tool-preview-title")
        yield Static("", id="tool-preview-detail")
        yield Input(placeholder="Rejection reason (optional)...", id="tool-reject-reason")
        yield Horizontal(
            Button("Approve", id="tool-approve", variant="success"),
            Button("Reject", id="tool-reject", variant="error"),
            id="tool-preview-buttons",
        )

    def show(self, tool_call: ToolCall) -> None:
        """Show tool call details for approval."""
        self.add_class("visible")
        self.query_one("#tool-preview-title", Static).update(
            f"[bold yellow]Tool Call: {tool_call.tool}[/bold yellow]"
        )
        # Format arguments with Rich markup for better readability
        args_text = json.dumps(tool_call.args, ensure_ascii=False, indent=2)
        highlighted = self._highlight_json(args_text)
        self.query_one("#tool-preview-detail", Static).update(
            f"[bold]Arguments:[/bold]\n{highlighted}"
        )
        # Clear rejection reason input
        self.query_one("#tool-reject-reason", Input).value = ""

    def hide(self) -> None:
        self.remove_class("visible")

    def _highlight_json(self, text: str) -> str:
        """Apply Rich markup to JSON text for syntax highlighting."""
        lines = []
        for line in text.split("\n"):
            stripped = line.strip()
            if ":" in stripped and not stripped.startswith(("{", "[", "}")):
                parts = line.split(":", 1)
                key = parts[0].rstrip()
                val = parts[1].lstrip() if len(parts) > 1 else ""
                lines.append(f"[bold cyan]{key}[/bold cyan]: [green]{val}[/green]")
            else:
                lines.append(f"[dim]{line}[/dim]")
        return "\n".join(lines)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "tool-approve":
            self.hide()
            self.post_message(self.Approved())
        elif event.button.id == "tool-reject":
            reason = self.query_one("#tool-reject-reason", Input).value.strip()
            self.hide()
            self.post_message(self.Rejected(reason))
