"""Left panel — CognitiveObject list widget."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import Label, ListItem, ListView, Static


STATUS_ICONS = {
    "created": "[dim]\u25cb[/dim]",
    "running": "[bold]\u25cf[/bold]",
    "paused": "[bold italic]\u23f3[/bold italic]",
    "completed": "[dim]\u2713[/dim]",
    "aborted": "[bold reverse]\u2717[/bold reverse]",
    "failed": "[bold reverse]\u2717[/bold reverse]",
}

# Filter cycle: All -> running -> paused -> completed -> created -> failed
FILTER_CYCLE = [None, "running", "paused", "completed", "created", "failed"]
FILTER_LABELS = {
    None: "All",
    "running": "Running",
    "paused": "Paused",
    "completed": "Completed",
    "created": "Created",
    "failed": "Failed",
}

MAX_TITLE_LEN = 32


class COListItem(ListItem):
    """A single CognitiveObject in the list."""

    def __init__(self, co_id: str, title: str, status: str, updated_at: str = "") -> None:
        super().__init__(classes="item-card")
        self.co_id = co_id
        self.co_title = title
        self.co_status = status
        self.co_updated_at = updated_at

    def compose(self) -> ComposeResult:
        icon = STATUS_ICONS.get(self.co_status, "\u25cb")
        display_title = self.co_title if len(self.co_title) <= MAX_TITLE_LEN else self.co_title[:MAX_TITLE_LEN - 1] + "\u2026"
        subtitle = f"[dim]{self.co_status}  {self.co_updated_at}[/dim]"
        yield Label(f"{icon} {display_title}\n{subtitle}", classes="item-label")


class COList(Static):
    """Left panel containing the list of CognitiveObjects."""

    class Selected(Message):
        """Emitted when a CO is selected."""
        def __init__(self, co_id: str) -> None:
            super().__init__()
            self.co_id = co_id

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._all_cos: list = []
        self._filter_index = 0  # index into FILTER_CYCLE

    @property
    def current_filter(self) -> str | None:
        return FILTER_CYCLE[self._filter_index]

    def compose(self) -> ComposeResult:
        yield Static("Cognitive Objects", classes="panel-title")
        yield Static("Filter: All", id="co-filter-label", classes="filter-label")
        yield ListView(id="co-listview")

    def cycle_filter(self) -> None:
        """Cycle to the next status filter."""
        self._filter_index = (self._filter_index + 1) % len(FILTER_CYCLE)
        f = self.current_filter
        label = FILTER_LABELS.get(f, "All")
        filtered = self._filtered_cos()
        self.query_one("#co-filter-label", Static).update(
            f"Filter: [bold]{label}[/bold] ({len(filtered)}/{len(self._all_cos)})"
        )
        self._render_list(filtered)

    def refresh_list(self, cos: list) -> None:
        """Refresh the list with CognitiveObject instances."""
        self._all_cos = cos
        f = self.current_filter
        label = FILTER_LABELS.get(f, "All")
        filtered = self._filtered_cos()
        self.query_one("#co-filter-label", Static).update(
            f"Filter: [bold]{label}[/bold] ({len(filtered)}/{len(self._all_cos)})"
        )
        self._render_list(filtered)

    def _filtered_cos(self) -> list:
        f = self.current_filter
        if f is None:
            return self._all_cos
        return [
            co for co in self._all_cos
            if (co.status.value if hasattr(co.status, 'value') else str(co.status)) == f
        ]

    def _render_list(self, cos: list) -> None:
        listview = self.query_one("#co-listview", ListView)
        listview.clear()
        for co in cos:
            status = co.status.value if hasattr(co.status, 'value') else str(co.status)
            updated = co.updated_at.strftime("%m-%d %H:%M") if co.updated_at else ""
            listview.append(COListItem(co.id, co.title, status, updated))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, COListItem):
            self.post_message(self.Selected(item.co_id))

    def select_next(self) -> None:
        """Move selection down in the list."""
        listview = self.query_one("#co-listview", ListView)
        if listview.index is None:
            if len(listview.children) > 0:
                listview.index = 0
        elif listview.index < len(listview.children) - 1:
            listview.index += 1
        self._emit_selected(listview)

    def select_prev(self) -> None:
        """Move selection up in the list."""
        listview = self.query_one("#co-listview", ListView)
        if listview.index is None:
            if len(listview.children) > 0:
                listview.index = 0
        elif listview.index > 0:
            listview.index -= 1
        self._emit_selected(listview)

    def _emit_selected(self, listview: ListView) -> None:
        if listview.index is not None:
            items = list(listview.children)
            if 0 <= listview.index < len(items):
                item = items[listview.index]
                if isinstance(item, COListItem):
                    self.post_message(self.Selected(item.co_id))

    def update_item_status(self, co_id: str, new_status: str) -> None:
        """Update a specific item's status display."""
        listview = self.query_one("#co-listview", ListView)
        for item in listview.children:
            if isinstance(item, COListItem) and item.co_id == co_id:
                item.co_status = new_status
                label = item.query_one(Label)
                icon = STATUS_ICONS.get(new_status, "\u25cb")
                display_title = item.co_title if len(item.co_title) <= MAX_TITLE_LEN else item.co_title[:MAX_TITLE_LEN - 1] + "\u2026"
                subtitle = f"[dim]{new_status}  {item.co_updated_at}[/dim]"
                label.update(f"{icon} {display_title}\n{subtitle}")
                break

    def mark_awaiting(self, co_id: str) -> None:
        """Add a visual indicator that a CO needs attention."""
        listview = self.query_one("#co-listview", ListView)
        for item in listview.children:
            if isinstance(item, COListItem) and item.co_id == co_id:
                label = item.query_one(Label)
                icon = STATUS_ICONS.get(item.co_status, "\u25cb")
                display_title = item.co_title if len(item.co_title) <= MAX_TITLE_LEN else item.co_title[:MAX_TITLE_LEN - 1] + "\u2026"
                subtitle = f"[dim]{item.co_status}  {item.co_updated_at}[/dim]"
                label.update(f"{icon} [bold reverse]![/bold reverse] {display_title}\n{subtitle}")
                break
