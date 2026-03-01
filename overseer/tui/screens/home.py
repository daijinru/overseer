"""Home screen — main screen with CO list + detail panel."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from overseer.tui.theme import FALLOUT_BANNER

from overseer.tui.widgets.co_detail import CODetail
from overseer.tui.widgets.co_list import COList
from overseer.tui.widgets.execution_log import ExecutionLog
from overseer.tui.widgets.interaction_panel import InteractionPanel
from overseer.tui.widgets.plan_progress import PlanProgress
from overseer.tui.widgets.tool_preview import ToolPreview


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
        ("a", "view_artifacts", "Artifacts"),
        ("y", "copy_log", "Copy Log"),
        ("m", "view_memories", "Memories"),
        ("w", "view_tools", "Tools"),
        ("i", "view_system", "System"),
        ("q", "quit_app", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(FALLOUT_BANNER, id="crt-banner")
        with Horizontal(id="home-container"):
            with Vertical(id="co-list-panel"):
                yield COList()
            with Vertical(id="detail-panel"):
                yield CODetail()
                yield PlanProgress(id="plan-progress-panel")
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

    def action_copy_log(self) -> None:
        try:
            log = self.query_one(ExecutionLog)
            log.copy_log()
        except Exception:
            pass

    def action_view_memories(self) -> None:
        self.app.action_view_memories()

    def action_view_artifacts(self) -> None:
        self.app.action_view_artifacts()

    def action_view_tools(self) -> None:
        self.app.action_view_tools()

    def action_view_system(self) -> None:
        self.app.action_view_system()

    async def action_quit_app(self) -> None:
        await self.app.action_quit()
