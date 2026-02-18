"""Interaction panel — HITL decision panel with dynamic options."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.message import Message
from textual.widgets import Button, Input, Static


class OptionButton(Button):
    """Button subclass that stores its option value cleanly."""

    def __init__(self, label: str, option_value: str, **kwargs) -> None:
        super().__init__(label, **kwargs)
        self.option_value = option_value


class InteractionPanel(Vertical):
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
            f"[bold reverse]Decision Required:[/bold reverse] {reason}"
        )

        # Filter out None/empty options and ensure we always have usable options
        valid_options = [opt for opt in (options or []) if opt]
        if not valid_options:
            valid_options = ["Continue", "Abort"]

        # Rebuild option buttons with OptionButton subclass
        container = self.query_one("#interaction-options", Horizontal)
        container.remove_children()
        for i, option in enumerate(valid_options):
            btn = OptionButton(
                f"[{i+1}] {option}",
                option_value=option,
                id=f"opt-{i}",
                variant="primary",
            )
            container.mount(btn)

        # Clear and focus input so user can type and press Enter
        inp = self.query_one("#interaction-input", Input)
        inp.value = ""
        inp.focus()

    def hide(self) -> None:
        """Hide the interaction panel."""
        self.remove_class("visible")
        # Remove dynamic buttons to prevent focus-chain errors during shutdown
        try:
            container = self.query_one("#interaction-options", Horizontal)
            container.remove_children()
        except Exception:
            pass
        # Blur the input to prevent focus issues during shutdown
        try:
            inp = self.query_one("#interaction-input", Input)
            inp.blur()
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if isinstance(event.button, OptionButton):
            text = self.query_one("#interaction-input", Input).value
            self.hide()
            self.post_message(self.Decision(event.button.option_value, text))

    def on_key(self, event: Key) -> None:
        """Handle number keys 1-9 as shortcuts to select options."""
        if not self.has_class("visible"):
            return
        if event.key in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
            index = int(event.key) - 1
            container = self.query_one("#interaction-options", Horizontal)
            buttons = [c for c in container.children if isinstance(c, OptionButton)]
            if 0 <= index < len(buttons):
                text = self.query_one("#interaction-input", Input).value
                self.hide()
                self.post_message(self.Decision(buttons[index].option_value, text))
                event.prevent_default()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Allow Enter in the input to submit user feedback as the decision."""
        text = event.value.strip()
        if not text:
            return
        # User wrote feedback — treat it as the primary intent,
        # don't attach an arbitrary default button choice.
        self.hide()
        self.post_message(self.Decision("feedback", text))
