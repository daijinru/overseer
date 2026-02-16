"""Right panel — CognitiveObject detail view."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Label, Static

from ceo.models.cognitive_object import CognitiveObject


class CODetail(Static):
    """Right panel showing CO details and execution history."""

    def compose(self) -> ComposeResult:
        yield Static(id="co-detail-header")
        yield Static("", id="co-detail-title")
        yield Static("", id="co-detail-status")
        yield Static("", id="co-detail-info")

    def show_co(self, co: CognitiveObject | None) -> None:
        """Display details for a CognitiveObject."""
        if co is None:
            self.query_one("#co-detail-title", Static).update("No event selected")
            self.query_one("#co-detail-status", Static).update("")
            self.query_one("#co-detail-info", Static).update(
                "Press [bold]n[/bold] to create a new cognitive object"
            )
            return

        self.query_one("#co-detail-title", Static).update(
            f"[bold]\u25b6 {co.title}[/bold]"
        )

        step_count = (co.context or {}).get("step_count", 0)
        self.query_one("#co-detail-status", Static).update(
            f"Status: [bold]{co.status.upper()}[/bold]  |  Steps: {step_count}"
        )

        desc = co.description or "No description"
        created = co.created_at.strftime("%Y-%m-%d %H:%M") if co.created_at else "?"
        self.query_one("#co-detail-info", Static).update(
            f"Created: {created}\n{desc}"
        )
