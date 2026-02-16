"""Tool preview panel — shows tool call details for human approval."""

from __future__ import annotations

import json

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, Static

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
        args_text = json.dumps(tool_call.args, ensure_ascii=False, indent=2)
        self.query_one("#tool-preview-detail", Static).update(
            f"Arguments:\n{args_text}"
        )

    def hide(self) -> None:
        self.remove_class("visible")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "tool-approve":
            self.hide()
            self.post_message(self.Approved())
        elif event.button.id == "tool-reject":
            self.hide()
            self.post_message(self.Rejected())
