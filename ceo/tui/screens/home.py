"""Home screen — main screen with CO list + detail panel."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header

from ceo.tui.widgets.co_detail import CODetail
from ceo.tui.widgets.co_list import COList
from ceo.tui.widgets.execution_log import ExecutionLog
from ceo.tui.widgets.interaction_panel import InteractionPanel
from ceo.tui.widgets.tool_preview import ToolPreview


class HomeScreen(Screen):
    """Main screen with CO list and detail view."""

    BINDINGS = [
        ("n", "new_co", "New"),
        ("s", "start_co", "Start"),
        ("c", "complete_co", "Complete"),
        ("x", "stop_co", "Stop"),
        ("d", "delete_co", "Delete"),
        ("D", "clear_all_co", "Clear All"),
        ("j", "next_co", "Next"),
        ("k", "prev_co", "Prev"),
        ("f", "filter_co", "Filter"),
        ("t", "view_tool_result", "Tool Result"),
        ("y", "copy_log", "Copy Log"),
        ("q", "quit_app", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="home-container"):
            with Vertical(id="co-list-panel"):
                yield COList()
            with Vertical(id="detail-panel"):
                yield CODetail()
                yield ExecutionLog(id="execution-log")
                yield ToolPreview(id="tool-preview-panel")
                yield InteractionPanel(id="interaction-panel")
        yield Footer()

    def action_new_co(self) -> None:
        self.app.action_new_co()

    def action_start_co(self) -> None:
        self.app.action_start_co()

    def action_stop_co(self) -> None:
        self.app.action_stop_co()

    def action_complete_co(self) -> None:
        self.app.action_complete_co()

    def action_delete_co(self) -> None:
        self.app.action_delete_co()

    def action_clear_all_co(self) -> None:
        self.app.action_clear_all_co()

    def action_next_co(self) -> None:
        self.app.action_next_co()

    def action_prev_co(self) -> None:
        self.app.action_prev_co()

    def action_filter_co(self) -> None:
        self.app.action_filter_co()

    def action_view_tool_result(self) -> None:
        try:
            log = self.query_one(ExecutionLog)
            log.show_tool_result_picker()
        except Exception:
            pass

    def action_copy_log(self) -> None:
        try:
            log = self.query_one(ExecutionLog)
            log.copy_log()
        except Exception:
            pass

    async def action_quit_app(self) -> None:
        await self.app.action_quit()
