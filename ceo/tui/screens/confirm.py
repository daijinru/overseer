"""Confirm screen — modal for confirming destructive actions."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class ConfirmScreen(ModalScreen):
    """Modal screen for confirming destructive actions."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title: str, message: str) -> None:
        super().__init__()
        self._title = title
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-container"):
            yield Label(f"[bold]{self._title}[/bold]", classes="confirm-title")
            yield Label(self._message, classes="confirm-message")
            with Horizontal(id="confirm-buttons"):
                yield Button("Confirm", id="confirm-ok", variant="error")
                yield Button("Cancel", id="confirm-cancel")

    def on_mount(self) -> None:
        self.query_one("#confirm-cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-ok":
            self.dismiss(True)
        elif event.button.id == "confirm-cancel":
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)
