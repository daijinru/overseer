"""Left panel — CognitiveObject list widget."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import Label, ListItem, ListView, Static


STATUS_ICONS = {
    "created": "[dim]\u25cb[/dim]",
    "running": "[green]\u25cf[/green]",
    "paused": "[yellow]\u23f3[/yellow]",
    "completed": "[blue]\u2713[/blue]",
    "aborted": "[red]\u2717[/red]",
    "failed": "[red]\u2717[/red]",
}


class COListItem(ListItem):
    """A single CognitiveObject in the list."""

    def __init__(self, co_id: str, title: str, status: str) -> None:
        super().__init__()
        self.co_id = co_id
        self.co_title = title
        self.co_status = status

    def compose(self) -> ComposeResult:
        icon = STATUS_ICONS.get(self.co_status, "\u25cb")
        yield Label(f"{icon} {self.co_title}", classes=f"co-status-{self.co_status}")


class COList(Static):
    """Left panel containing the list of CognitiveObjects."""

    class Selected(Message):
        """Emitted when a CO is selected."""
        def __init__(self, co_id: str) -> None:
            super().__init__()
            self.co_id = co_id

    def compose(self) -> ComposeResult:
        yield Static("Cognitive Objects", classes="panel-title")
        yield ListView(id="co-listview")

    def refresh_list(self, cos: list) -> None:
        """Refresh the list with CognitiveObject instances."""
        listview = self.query_one("#co-listview", ListView)
        listview.clear()
        for co in cos:
            status = co.status.value if hasattr(co.status, 'value') else str(co.status)
            listview.append(COListItem(co.id, co.title, status))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
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
                label.update(f"{icon} {item.co_title}")
                break
