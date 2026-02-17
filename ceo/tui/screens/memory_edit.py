"""Memory edit screen — modal for creating or editing a memory."""

from __future__ import annotations

from typing import Any, Dict, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, TextArea

CATEGORIES = [
    ("preference", "preference"),
    ("lesson", "lesson"),
    ("domain_knowledge", "domain_knowledge"),
    ("decision_pattern", "decision_pattern"),
]


class MemoryEditScreen(ModalScreen):
    """Modal screen for creating or editing a memory.

    Dismisses with a dict {"category", "content", "tags"} on save, or None on cancel.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, existing: Optional[Dict[str, Any]] = None) -> None:
        super().__init__()
        self._existing = existing  # None = create mode

    @property
    def _is_edit(self) -> bool:
        return self._existing is not None

    def compose(self) -> ComposeResult:
        title = "Edit Memory" if self._is_edit else "New Memory"
        with Vertical(id="memory-edit-container"):
            yield Label(f"[bold]{title}[/bold]", classes="title")
            yield Label("Category:")
            yield Select(
                CATEGORIES,
                id="memory-edit-category",
                value=self._existing["category"] if self._is_edit else "lesson",
            )
            yield Label("Content:")
            yield TextArea(
                self._existing["content"] if self._is_edit else "",
                id="memory-edit-content",
            )
            yield Label("Tags (comma separated):")
            yield Input(
                placeholder="e.g. python, debugging, api",
                value=", ".join(self._existing["tags"]) if self._is_edit and self._existing.get("tags") else "",
                id="memory-edit-tags",
            )
            with Horizontal(id="memory-edit-buttons"):
                yield Button("Save", id="memory-edit-save", variant="primary")
                yield Button("Cancel", id="memory-edit-cancel")

    def on_mount(self) -> None:
        self.query_one("#memory-edit-content", TextArea).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "memory-edit-save":
            self._do_save()
        elif event.button.id == "memory-edit-cancel":
            self.dismiss(None)

    def _do_save(self) -> None:
        content = self.query_one("#memory-edit-content", TextArea).text.strip()
        if not content:
            self.notify("Content cannot be empty", severity="error")
            return
        category = self.query_one("#memory-edit-category", Select).value
        tags_raw = self.query_one("#memory-edit-tags", Input).value.strip()
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
        self.dismiss({"category": category, "content": content, "tags": tags})

    def action_cancel(self) -> None:
        self.dismiss(None)
