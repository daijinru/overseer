"""CeoApp — main Textual application, wires TUI to services."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from textual.app import App
from textual.binding import Binding
from textual.message import Message
from textual.worker import Worker, WorkerState

from ceo.config import load_config
from ceo.core.enums import COStatus
from ceo.core.protocols import ToolCall
from ceo.database import init_db
from ceo.models.execution import Execution
from ceo.services.cognitive_object_service import CognitiveObjectService
from ceo.services.execution_service import ExecutionService
from ceo.tui.screens.confirm import ConfirmScreen
from ceo.tui.screens.create import CreateScreen
from ceo.tui.screens.home import HomeScreen
from ceo.tui.screens.memory import MemoryScreen
from ceo.tui.screens.artifact_viewer import ArtifactListScreen
from ceo.tui.screens.tool_panel import ToolPanelScreen
from ceo.tui.theme import FALLOUT_THEME
from ceo.tui.widgets.co_detail import CODetail
from ceo.tui.widgets.co_list import COList
from ceo.tui.widgets.execution_log import ExecutionLog
from ceo.tui.widgets.interaction_panel import InteractionPanel
from ceo.tui.widgets.tool_preview import ToolPreview

logger = logging.getLogger(__name__)

CSS_PATH = Path(__file__).parent / "styles" / "app.tcss"


# ── Custom Messages for async worker → app communication ──
# Worker runs as async coroutine in the same event loop,
# so we use post_message() instead of call_from_thread().

class StepUpdate(Message):
    def __init__(self, exec_id: str, co_id: str, phase: str) -> None:
        super().__init__()
        self.exec_id = exec_id
        self.co_id = co_id
        self.phase = phase


class HumanRequired(Message):
    def __init__(self, co_id: str, reason: str, options: List[str]) -> None:
        super().__init__()
        self.co_id = co_id
        self.reason = reason
        self.options = options


class ToolConfirmRequired(Message):
    def __init__(self, co_id: str, tool_name: str, tool_args: Dict[str, Any]) -> None:
        super().__init__()
        self.co_id = co_id
        self.tool_name = tool_name
        self.tool_args = tool_args


class ExecutionComplete(Message):
    def __init__(self, co_id: str, status: str) -> None:
        super().__init__()
        self.co_id = co_id
        self.status = status


class ExecutionError(Message):
    def __init__(self, co_id: str, error: str) -> None:
        super().__init__()
        self.co_id = co_id
        self.error = error


class InfoMessage(Message):
    def __init__(self, co_id: str, text: str) -> None:
        super().__init__()
        self.co_id = co_id
        self.text = text


class CeoApp(App):
    """Wenko CEO — Cognitive Operating System."""

    TITLE = "WENKO CEO v2.0.76"
    SUB_TITLE = "ROBCO INDUSTRIES TERMLINK // Cognitive Operating System"
    CSS_PATH = CSS_PATH

    # App-level bindings are hidden from Footer (show=False).
    # Each Screen defines its own visible BINDINGS for the Footer.
    BINDINGS = [
        Binding("n", "new_co", "New", show=False),
        Binding("s", "start_co", "Start", show=False),
        Binding("c", "complete_co", "Complete", show=False),
        Binding("x", "stop_co", "Stop", show=False),
        Binding("d", "delete_co", "Delete", show=False),
        Binding("D", "clear_all_co", "Clear All", show=False),
        Binding("j", "next_co", "Next", show=False),
        Binding("k", "prev_co", "Prev", show=False),
        Binding("f", "filter_co", "Filter", show=False),
        Binding("a", "view_artifacts", "Artifacts", show=False),
        Binding("m", "view_memories", "Memories", show=False),
        Binding("w", "view_tools", "Tools", show=False),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        load_config()
        init_db()
        self.register_theme(FALLOUT_THEME)
        self.theme = "fallout"
        self._co_service = CognitiveObjectService()
        self._selected_co_id: str | None = None
        self._execution_services: dict[str, ExecutionService] = {}
        self._co_workers: dict[str, object] = {}
        self._awaiting_count = 0
        self._shutting_down = False

    def on_mount(self) -> None:
        self.push_screen(HomeScreen())
        self.call_after_refresh(self._refresh_co_list)

    # ── CO List ──

    def _refresh_co_list(self) -> None:
        if self._shutting_down:
            return
        self._co_service.session.expire_all()
        cos = self._co_service.list_all()
        try:
            co_list = self.screen.query_one(COList)
            co_list.refresh_list(cos)
        except Exception:
            logger.debug("COList widget not available yet", exc_info=True)

        self._awaiting_count = sum(
            1 for co in cos if co.status == "paused"
        )
        self._update_subtitle(cos)

    def on_colist_selected(self, message: COList.Selected) -> None:
        self._selected_co_id = message.co_id
        self._show_co_detail(message.co_id)

    def _show_co_detail(self, co_id: str) -> None:
        if self._shutting_down:
            return
        # If this CO has a running ExecutionService, use its session
        # to see the latest execution data; otherwise use the app session.
        exec_service = self._execution_services.get(co_id)
        if exec_service:
            co = exec_service.co_service.get(co_id)
        else:
            self._co_service.session.expire_all()
            co = self._co_service.get(co_id)
        if co is None:
            return
        try:
            detail = self.screen.query_one(CODetail)
            detail.show_co(co)
        except Exception:
            logger.debug("CODetail widget not available", exc_info=True)
        try:
            log = self.screen.query_one(ExecutionLog)
            log.show_executions(list(co.executions))
        except Exception:
            logger.debug("ExecutionLog widget not available", exc_info=True)

    # ── Actions ──

    def action_new_co(self) -> None:
        def on_create_result(result) -> None:
            if result is not None:
                co = self._co_service.create(
                    title=result["title"],
                    description=result["description"],
                )
                self._selected_co_id = co.id
                self._refresh_co_list()
                self._show_co_detail(co.id)
                self.notify(f"Created: {co.title}")

        self.push_screen(CreateScreen(), callback=on_create_result)

    def action_start_co(self) -> None:
        if self._selected_co_id is None:
            self.notify("No event selected", severity="warning")
            return

        co = self._co_service.get(self._selected_co_id)
        if co is None:
            self.notify("Event not found", severity="error")
            return

        if co.status not in ("created", "paused"):
            self.notify(f"Cannot start event in '{co.status}' status", severity="warning")
            return

        co_id = self._selected_co_id
        self.notify(f"Starting: {co.title}")

        # Create execution service for this CO
        exec_service = ExecutionService()
        self._execution_services[co_id] = exec_service

        # Set up callbacks that use post_message (safe from async worker)
        app = self
        exec_service.set_callbacks(
            on_step_update=lambda ex, phase: app.post_message(
                StepUpdate(ex.id, ex.cognitive_object_id, phase)
            ),
            on_human_required=lambda ex, reason, options: app.post_message(
                HumanRequired(ex.cognitive_object_id, reason, options)
            ),
            on_tool_confirm=lambda ex, tc: app.post_message(
                ToolConfirmRequired(ex.cognitive_object_id, tc.tool, tc.args)
            ),
            on_complete=lambda cid, status: app.post_message(
                ExecutionComplete(cid, status)
            ),
            on_error=lambda err: app.post_message(
                ExecutionError(co_id, err)
            ),
            on_info=lambda cid, text: app.post_message(
                InfoMessage(cid, text)
            ),
        )

        # Run the cognitive loop in an async worker (same event loop)
        worker = self.run_worker(
            exec_service.run_loop(co_id),
            name=f"exec-{co_id[:8]}",
            exclusive=False,
        )
        self._co_workers[co_id] = worker

        self._refresh_co_list()

    def action_stop_co(self) -> None:
        if self._selected_co_id is None:
            self.notify("No event selected", severity="warning")
            return

        co_id = self._selected_co_id
        if co_id not in self._execution_services:
            self.notify("Event is not running", severity="warning")
            return

        # Cancel the worker — triggers CancelledError in run_loop,
        # which sets the CO status to paused.
        worker = self._co_workers.get(co_id)
        if worker:
            worker.cancel()

        self.notify("Stopping event...")

    def action_complete_co(self) -> None:
        if self._selected_co_id is None:
            self.notify("No event selected", severity="warning")
            return

        co_id = self._selected_co_id

        # If running, stop the worker first
        if co_id in self._execution_services:
            worker = self._co_workers.get(co_id)
            if worker:
                worker.cancel()
            self._execution_services.pop(co_id, None)
            self._co_workers.pop(co_id, None)

        co = self._co_service.get(co_id)
        if co is None:
            self.notify("Event not found", severity="error")
            return

        if co.status == "completed":
            self.notify("Event already completed", severity="warning")
            return

        self._co_service.update_status(co_id, COStatus.COMPLETED)
        self._refresh_co_list()
        self._show_co_detail(co_id)
        self.notify(f"Completed: {co.title}")

    def action_delete_co(self) -> None:
        if self._selected_co_id is None:
            self.notify("No event selected", severity="warning")
            return

        if self._selected_co_id in self._execution_services:
            self.notify("Cannot delete a running event", severity="warning")
            return

        co = self._co_service.get(self._selected_co_id)
        if co is None:
            self.notify("Event not found", severity="error")
            return

        title = co.title
        co_id = self._selected_co_id

        def on_confirm(confirmed: bool) -> None:
            if not confirmed:
                return
            self._co_service.delete(co_id)
            self._selected_co_id = None
            self._refresh_co_list()
            try:
                detail = self.screen.query_one(CODetail)
                detail.show_co(None)
            except Exception:
                pass
            self.notify(f"Deleted: {title}")

        self.push_screen(
            ConfirmScreen("Delete Event", f"Delete \"{title}\"?"),
            callback=on_confirm,
        )

    def action_clear_all_co(self) -> None:
        if self._execution_services:
            self.notify("Cannot clear while events are running", severity="warning")
            return

        cos = self._co_service.list_all()
        count = len(cos)
        if count == 0:
            self.notify("No events to clear", severity="warning")
            return

        def on_confirm(confirmed: bool) -> None:
            if not confirmed:
                return
            deleted = self._co_service.delete_all()
            self._selected_co_id = None
            self._refresh_co_list()
            try:
                detail = self.screen.query_one(CODetail)
                detail.show_co(None)
            except Exception:
                pass
            self.notify(f"Cleared {deleted} events")

        self.push_screen(
            ConfirmScreen("Clear All Events", f"Delete all {count} events? This cannot be undone."),
            callback=on_confirm,
        )

    def action_next_co(self) -> None:
        """Move selection down in the CO list."""
        try:
            co_list = self.screen.query_one(COList)
            co_list.select_next()
        except Exception:
            pass

    def action_prev_co(self) -> None:
        """Move selection up in the CO list."""
        try:
            co_list = self.screen.query_one(COList)
            co_list.select_prev()
        except Exception:
            pass

    def action_filter_co(self) -> None:
        """Cycle the status filter on the CO list."""
        try:
            co_list = self.screen.query_one(COList)
            co_list.cycle_filter()
        except Exception:
            pass

    def action_view_memories(self) -> None:
        """Open the Memory browser screen."""
        self.push_screen(MemoryScreen())

    def action_view_artifacts(self) -> None:
        """Open the Artifact viewer for the selected CO."""
        if self._selected_co_id is None:
            self.notify("No event selected", severity="warning")
            return

        co = self._co_service.get(self._selected_co_id)
        if co is None:
            self.notify("Event not found", severity="error")
            return

        artifacts = list(co.artifacts) if co.artifacts else []
        if not artifacts:
            self.notify("No artifacts for this event", severity="warning")
            return

        self.push_screen(ArtifactListScreen(artifacts))

    def action_view_tools(self) -> None:
        """Open the Tool panel to browse registered tools."""
        from ceo.services.tool_service import ToolService

        tools: list = []
        servers: list = []
        live_ts = None

        # Try to get data from a running ExecutionService (has live MCP connections)
        for exec_service in self._execution_services.values():
            live_ts = exec_service.tool_service
            tools = live_ts.list_tools_detailed()
            servers = live_ts.list_configured_servers()
            break

        if not tools:
            # No running service — show builtin tools + server config
            ts = ToolService()
            tools = ts.list_tools_detailed()
            servers = ts.list_configured_servers()

        self.push_screen(ToolPanelScreen(tools, servers=servers, tool_service=live_ts))

    # ── Message handlers from execution service ──

    def on_step_update(self, message: StepUpdate) -> None:
        if self._shutting_down:
            return
        # Use the ExecutionService's own session to read its Execution objects
        exec_service = self._execution_services.get(message.co_id)
        if exec_service is None:
            return
        ex = exec_service.session.get(Execution, message.exec_id)
        if ex is None:
            return

        if message.co_id == self._selected_co_id:
            try:
                log = self.screen.query_one(ExecutionLog)
                log.add_step(ex, message.phase)
            except Exception:
                logger.debug("ExecutionLog widget not available", exc_info=True)

        try:
            co_list = self.screen.query_one(COList)
            co = exec_service.co_service.get(message.co_id)
            if co:
                co_list.update_item_status(message.co_id, co.status.value)
        except Exception:
            logger.debug("COList widget not available", exc_info=True)

    def on_human_required(self, message: HumanRequired) -> None:
        if self._shutting_down:
            return
        self._awaiting_count += 1
        self._update_subtitle()

        if message.co_id == self._selected_co_id:
            try:
                panel = self.screen.query_one(InteractionPanel)
                options = message.options if message.options else ["Continue", "Abort"]
                panel.show(message.reason, options)
            except Exception:
                logger.debug("InteractionPanel widget not available", exc_info=True)
        else:
            # Notify user about non-selected CO needing attention
            self.notify(
                f"Event {message.co_id[:8]} needs your input",
                severity="warning",
            )
            try:
                co_list = self.screen.query_one(COList)
                co_list.mark_awaiting(message.co_id)
            except Exception:
                logger.debug("COList widget not available", exc_info=True)

        self._refresh_co_list()

    def on_tool_confirm_required(self, message: ToolConfirmRequired) -> None:
        if self._shutting_down:
            return
        if message.co_id == self._selected_co_id:
            try:
                preview = self.screen.query_one(ToolPreview)
                preview.show(ToolCall(tool=message.tool_name, args=message.tool_args))
            except Exception:
                logger.debug("ToolPreview widget not available", exc_info=True)

    def on_execution_complete(self, message: ExecutionComplete) -> None:
        self._execution_services.pop(message.co_id, None)
        self._co_workers.pop(message.co_id, None)
        if self._shutting_down:
            return
        self.notify(f"Event {message.status}: {message.co_id[:8]}")
        self._refresh_co_list()
        if message.co_id == self._selected_co_id:
            self._show_co_detail(message.co_id)

    def on_execution_error(self, message: ExecutionError) -> None:
        self._execution_services.pop(message.co_id, None)
        self._co_workers.pop(message.co_id, None)
        if self._shutting_down:
            return
        self.notify(f"Error: {message.error}", severity="error")
        # Write error to execution log for persistence
        if message.co_id == self._selected_co_id:
            try:
                log = self.screen.query_one(ExecutionLog)
                log.add_error(message.error)
            except Exception:
                logger.debug("ExecutionLog widget not available", exc_info=True)
        self._refresh_co_list()

    def on_info_message(self, message: InfoMessage) -> None:
        if self._shutting_down:
            return
        if message.co_id == self._selected_co_id:
            try:
                log = self.screen.query_one(ExecutionLog)
                log.add_info(message.text)
            except Exception:
                logger.debug("ExecutionLog widget not available", exc_info=True)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Clean up when a worker is cancelled (stopped by user)."""
        if event.state == WorkerState.CANCELLED:
            # Find and clean up the cancelled CO
            co_id = None
            for cid, worker in list(self._co_workers.items()):
                if worker is event.worker:
                    co_id = cid
                    break
            if co_id:
                self._execution_services.pop(co_id, None)
                self._co_workers.pop(co_id, None)
                if self._shutting_down:
                    return
                self.notify(f"Stopped: {co_id[:8]}")
                self._refresh_co_list()
                if co_id == self._selected_co_id:
                    self._show_co_detail(co_id)

    async def action_quit(self) -> None:
        """Gracefully shut down all MCP connections before quitting."""
        self._shutting_down = True
        for worker in list(self._co_workers.values()):
            worker.cancel()
        for exec_service in list(self._execution_services.values()):
            try:
                await exec_service.tool_service.disconnect()
            except Exception as e:
                logger.debug("Error disconnecting MCP on quit: %s", e)
        self._execution_services.clear()
        self._co_workers.clear()
        self.exit()

    # ── Handle interaction panel decisions ──

    def on_interaction_panel_decision(self, message: InteractionPanel.Decision) -> None:
        if self._selected_co_id and self._selected_co_id in self._execution_services:
            exec_service = self._execution_services[self._selected_co_id]
            exec_service.provide_human_response(message.choice, message.text)
            self._awaiting_count = max(0, self._awaiting_count - 1)
            self._update_subtitle()
            # Show user's HITL decision in the execution log
            try:
                log = self.screen.query_one(ExecutionLog)
                log.add_human_decision(message.choice, message.text)
            except Exception:
                pass

    def on_tool_preview_approved(self, message: ToolPreview.Approved) -> None:
        if self._selected_co_id and self._selected_co_id in self._execution_services:
            exec_service = self._execution_services[self._selected_co_id]
            exec_service.provide_human_response("approve")
            # Show tool approval in execution log
            try:
                log = self.screen.query_one(ExecutionLog)
                log.add_tool_approval(approved=True)
            except Exception:
                pass

    def on_tool_preview_rejected(self, message: ToolPreview.Rejected) -> None:
        if self._selected_co_id and self._selected_co_id in self._execution_services:
            exec_service = self._execution_services[self._selected_co_id]
            exec_service.provide_human_response("reject", message.reason)
            # Show tool rejection in execution log
            try:
                log = self.screen.query_one(ExecutionLog)
                log.add_tool_approval(approved=False, reason=message.reason)
            except Exception:
                pass

    def _update_subtitle(self, cos: list | None = None) -> None:
        """Update subtitle with comprehensive status counts."""
        if cos is None:
            self._co_service.session.expire_all()
            cos = self._co_service.list_all()

        total = len(cos)
        running = sum(1 for co in cos if (co.status.value if hasattr(co.status, 'value') else co.status) == "running")
        paused = sum(1 for co in cos if (co.status.value if hasattr(co.status, 'value') else co.status) == "paused")

        parts = ["ROBCO TERMLINK //"]
        stats = []
        if total > 0:
            stats.append(f"Total: {total}")
        if running > 0:
            stats.append(f"Running: {running}")
        if paused > 0:
            stats.append(f"Paused: {paused}")
        if self._awaiting_count > 0:
            stats.append(f"Awaiting: {self._awaiting_count}")

        if stats:
            parts.append("  |  " + "  |  ".join(stats))

        self.sub_title = "".join(parts)
