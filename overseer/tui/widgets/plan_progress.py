"""Plan progress widget — displays subtask list with status indicators."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static


# Status → (icon, rich style)
_STATUS_DISPLAY = {
    "completed": ("\u2713", "dim"),         # ✓
    "in_progress": ("\u25cf", "bold"),       # ●
    "pending": ("\u25cb", "dim"),            # ○
    "skipped": ("\u2717", "dim strike"),     # ✗
}


class PlanProgress(Static):
    """Compact panel showing the current task plan and subtask statuses."""

    def compose(self) -> ComposeResult:
        yield Static("", id="plan-progress-content")

    def update_plan(self, plan: dict | None) -> None:
        """Refresh the display from a plan dict (co.context['plan']).

        Call with None or empty dict to hide the panel.
        """
        content = self.query_one("#plan-progress-content", Static)

        if not plan:
            self.add_class("hidden")
            self.remove_class("visible")
            content.update("")
            return

        subtasks = plan.get("subtasks", [])
        if not subtasks:
            self.add_class("hidden")
            self.remove_class("visible")
            content.update("")
            return

        # Show the panel
        self.remove_class("hidden")
        self.add_class("visible")

        # Count progress
        completed = sum(1 for st in subtasks if st.get("status") == "completed")
        skipped = sum(1 for st in subtasks if st.get("status") == "skipped")
        total = len(subtasks)
        done = completed + skipped

        # Build border title
        self.border_title = f"Plan ({done}/{total})"

        # Build subtask lines
        lines = []
        for st in subtasks:
            status = st.get("status", "pending")
            icon, style = _STATUS_DISPLAY.get(status, ("\u25cb", "dim"))
            sid = st.get("id", "?")
            title = st.get("title", "")

            line = f"  [{style}]{icon}[/{style}] {sid}. {title}"

            # Show result summary for completed subtasks (truncated)
            summary = st.get("result_summary", "")
            if summary and status in ("completed", "skipped"):
                short = summary[:40] + ("..." if len(summary) > 40 else "")
                line += f"  [dim]\u2192 {short}[/dim]"

            # Mark current subtask
            if status == "in_progress":
                line += "  [bold]\u25c0 current[/bold]"

            lines.append(line)

        # Strategy line (if present)
        strategy = plan.get("overall_strategy", "")
        if strategy:
            lines.append(f"\n  [dim]Strategy: {strategy[:60]}{'...' if len(strategy) > 60 else ''}[/dim]")

        content.update("\n".join(lines))
