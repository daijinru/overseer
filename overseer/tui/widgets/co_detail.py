"""Right panel — CognitiveObject detail view."""

from __future__ import annotations

from datetime import datetime, timezone

from textual.app import ComposeResult
from textual.widgets import Static

from overseer.models.cognitive_object import CognitiveObject


STATUS_BADGES = {
    "created": "[dim]\u25cb CREATED[/dim]",
    "running": "[bold]\u25cf RUNNING[/bold]",
    "paused": "[bold italic]\u23f3 PAUSED[/bold italic]",
    "completed": "[dim]\u2713 COMPLETED[/dim]",
    "aborted": "[bold reverse]\u2717 ABORTED[/bold reverse]",
    "failed": "[bold reverse]\u2717 FAILED[/bold reverse]",
}


class CODetail(Static):
    """Right panel showing CO details and execution history."""

    def compose(self) -> ComposeResult:
        yield Static("", id="co-detail-header")
        yield Static("", id="co-detail-title")
        yield Static("", id="co-detail-meta")
        yield Static("", id="co-detail-stats")
        yield Static("", id="co-detail-info")
        yield Static("", id="co-detail-artifacts")

    def show_co(self, co: CognitiveObject | None) -> None:
        """Display details for a CognitiveObject."""
        if co is None:
            self.query_one("#co-detail-header", Static).update("")
            self.query_one("#co-detail-title", Static).update("No event selected")
            self.query_one("#co-detail-meta", Static).update("")
            self.query_one("#co-detail-stats", Static).update("")
            self.query_one("#co-detail-info", Static).update(
                "Press [bold]n[/bold] to create a new cognitive object"
            )
            self.query_one("#co-detail-artifacts", Static).update("")
            return

        # Header: status badge + short ID
        status_str = co.status.value if hasattr(co.status, 'value') else str(co.status)
        badge = STATUS_BADGES.get(status_str, status_str.upper())
        short_id = co.id[:8] if co.id else "?"
        self.query_one("#co-detail-header", Static).update(
            f"{badge}  [dim]#{short_id}[/dim]"
        )

        # Title
        self.query_one("#co-detail-title", Static).update(
            f"[bold]\u25b6 {co.title}[/bold]"
        )

        # Meta: timestamps and duration
        created = co.created_at.strftime("%Y-%m-%d %H:%M") if co.created_at else "?"
        updated = co.updated_at.strftime("%Y-%m-%d %H:%M") if co.updated_at else "-"
        duration = self._calc_duration(co)
        self.query_one("#co-detail-meta", Static).update(
            f"Created: {created}  |  Updated: {updated}  |  Duration: {duration}"
        )

        # Stats: steps, artifacts, context info
        step_count = (co.context or {}).get("step_count", 0)
        artifact_count = len(co.artifacts) if co.artifacts else 0
        self.query_one("#co-detail-stats", Static).update(
            f"Steps: [bold]{step_count}[/bold]  |  Artifacts: [bold]{artifact_count}[/bold]"
        )

        # Description
        desc = co.description or "[dim]No description[/dim]"
        self.query_one("#co-detail-info", Static).update(desc)

        # Artifacts list
        if co.artifacts:
            lines = ["[bold]Artifacts:[/bold]"]
            for art in co.artifacts[:5]:
                type_badge = f"[dim]{art.artifact_type}[/dim]" if art.artifact_type else ""
                lines.append(f"  \u2514\u2500 {art.name} {type_badge}")
            if len(co.artifacts) > 5:
                lines.append(f"  [dim]... and {len(co.artifacts) - 5} more[/dim]")
            self.query_one("#co-detail-artifacts", Static).update("\n".join(lines))
        else:
            self.query_one("#co-detail-artifacts", Static).update("")

    def _calc_duration(self, co: CognitiveObject) -> str:
        """Calculate duration string for a CO."""
        if not co.created_at:
            return "-"
        status_str = co.status.value if hasattr(co.status, 'value') else str(co.status)
        if status_str == "running":
            end = datetime.now(timezone.utc) if co.created_at.tzinfo else datetime.now()
        elif co.updated_at:
            end = co.updated_at
        else:
            return "-"
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
