"""Interaction panel — HITL decision panel with dynamic options."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, Input, Static


class InteractionPanel(Static):
    """Panel for human-in-the-loop decisions."""

    class Decision(Message):
        """Emitted when user makes a decision."""
        def __init__(self, choice: str, text: str = "") -> None:
            super().__init__()
            self.choice = choice
            self.text = text

    def compose(self) -> ComposeResult:
        yield Static("", id="interaction-reason")
        yield Horizontal(id="interaction-options")
        yield Input(placeholder="Optional feedback...", id="interaction-input")

    def show(self, reason: str, options: list[str]) -> None:
        """Show the interaction panel with a reason and options."""
        self.add_class("visible")
        self.query_one("#interaction-reason", Static).update(
            f"[bold yellow]Decision Required:[/bold yellow] {reason}"
        )

        # Rebuild option buttons
        container = self.query_one("#interaction-options", Horizontal)
        container.remove_children()
        for i, option in enumerate(options):
            btn = Button(f"[{i+1}] {option}", id=f"opt-{i}", variant="primary")
            btn._option_value = option  # store the option text
            container.mount(btn)

        # Clear and focus input
        inp = self.query_one("#interaction-input", Input)
        inp.value = ""

    def hide(self) -> None:
        """Hide the interaction panel."""
        self.remove_class("visible")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id and event.button.id.startswith("opt-"):
            option_value = getattr(event.button, "_option_value", "continue")
            text = self.query_one("#interaction-input", Input).value
            self.hide()
            self.post_message(self.Decision(option_value, text))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Allow Enter in the input to submit with the first option as default."""
        text = event.value.strip()
        if not text:
            return
        # Use the first option as the default choice
        container = self.query_one("#interaction-options", Horizontal)
        buttons = [c for c in container.children if isinstance(c, Button)]
        if buttons:
            option_value = getattr(buttons[0], "_option_value", "continue")
        else:
            option_value = "continue"
        self.hide()
        self.post_message(self.Decision(option_value, text))
