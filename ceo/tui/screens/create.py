"""Create screen — modal for creating a new CognitiveObject."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, TextArea


class CreateScreen(ModalScreen):
    """Modal screen for creating a new CognitiveObject."""

    class Created(Message):
        """Emitted when a new CO is created."""
        def __init__(self, title: str, description: str) -> None:
            super().__init__()
            self.title = title
            self.description = description

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="create-container"):
            yield Label("[bold]New Cognitive Object[/bold]", classes="title")
            yield Label("Goal / Title:")
            yield Input(placeholder="e.g. Investigate Q4 financial report anomalies", id="create-title")
            yield Label("Description (optional):")
            yield TextArea(id="create-description")
            with Horizontal(id="create-buttons"):
                yield Button("Create", id="create-ok", variant="primary")
                yield Button("Cancel", id="create-cancel")

    def on_mount(self) -> None:
        self.query_one("#create-title", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create-ok":
            self._do_create()
        elif event.button.id == "create-cancel":
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "create-title":
            self._do_create()

    def _do_create(self) -> None:
        title = self.query_one("#create-title", Input).value.strip()
        if not title:
            self.notify("Title cannot be empty", severity="error")
            return
        description = self.query_one("#create-description", TextArea).text.strip()
        self.dismiss({"title": title, "description": description})

    def action_cancel(self) -> None:
        self.dismiss(None)
