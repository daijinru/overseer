"""CeoApp — main Textual application, wires TUI to services."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from textual.app import App
from textual.message import Message
from textual.worker import Worker, WorkerState

from ceo.config import load_config
from ceo.core.enums import COStatus
from ceo.core.protocols import ToolCall
from ceo.database import init_db
from ceo.models.execution import Execution
from ceo.services.cognitive_object_service import CognitiveObjectService
from ceo.services.execution_service import ExecutionService
from ceo.tui.screens.create import CreateScreen
from ceo.tui.screens.home import HomeScreen
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


class CeoApp(App):
    """Wenko CEO — Cognitive Operating System."""

    TITLE = "Wenko CEO"
    SUB_TITLE = "Cognitive Operating System"
    CSS_PATH = CSS_PATH

    BINDINGS = [
        ("n", "new_co", "New"),
        ("s", "start_co", "Start"),
        ("c", "complete_co", "Complete"),
        ("x", "stop_co", "Stop"),
        ("d", "delete_co", "Delete"),
        ("D", "clear_all_co", "Clear All"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        load_config()
        init_db()
        self._co_service = CognitiveObjectService()
        self._selected_co_id: str | None = None
        self._execution_services: dict[str, ExecutionService] = {}
        self._co_workers: dict[str, object] = {}
        self._awaiting_count = 0

    def on_mount(self) -> None:
        self.push_screen(HomeScreen())
        self.call_after_refresh(self._refresh_co_list)

    # ── CO List ──

    def _refresh_co_list(self) -> None:
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
        self._update_footer_awaiting()

    def on_colist_selected(self, message: COList.Selected) -> None:
        self._selected_co_id = message.co_id
        self._show_co_detail(message.co_id)

    def _show_co_detail(self, co_id: str) -> None:
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
            self.notify("未选中任何事件", severity="warning")
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
            self.notify("事件未找到", severity="error")
            return

        if co.status == "completed":
            self.notify("事件已完成", severity="warning")
            return

        self._co_service.update_status(co_id, COStatus.COMPLETED)
        self._refresh_co_list()
        self._show_co_detail(co_id)
        self.notify(f"已完成: {co.title}")

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
        self._co_service.delete(self._selected_co_id)
        self._selected_co_id = None
        self._refresh_co_list()
        try:
            detail = self.screen.query_one(CODetail)
            detail.show_co(None)
        except Exception:
            pass
        self.notify(f"Deleted: {title}")

    def action_clear_all_co(self) -> None:
        if self._execution_services:
            self.notify("Cannot clear while events are running", severity="warning")
            return

        count = self._co_service.delete_all()
        self._selected_co_id = None
        self._refresh_co_list()
        try:
            detail = self.screen.query_one(CODetail)
            detail.show_co(None)
        except Exception:
            pass
        self.notify(f"Cleared {count} events")

    # ── Message handlers from execution service ──

    def on_step_update(self, message: StepUpdate) -> None:
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
        self._awaiting_count += 1
        self._update_footer_awaiting()

        if message.co_id == self._selected_co_id:
            try:
                panel = self.screen.query_one(InteractionPanel)
                options = message.options if message.options else ["Continue", "Abort"]
                panel.show(message.reason, options)
            except Exception:
                logger.debug("InteractionPanel widget not available", exc_info=True)

        self._refresh_co_list()

    def on_tool_confirm_required(self, message: ToolConfirmRequired) -> None:
        if message.co_id == self._selected_co_id:
            try:
                preview = self.screen.query_one(ToolPreview)
                preview.show(ToolCall(tool=message.tool_name, args=message.tool_args))
            except Exception:
                logger.debug("ToolPreview widget not available", exc_info=True)

    def on_execution_complete(self, message: ExecutionComplete) -> None:
        self.notify(f"Event {message.status}: {message.co_id[:8]}")
        self._execution_services.pop(message.co_id, None)
        self._co_workers.pop(message.co_id, None)
        self._refresh_co_list()
        if message.co_id == self._selected_co_id:
            self._show_co_detail(message.co_id)

    def on_execution_error(self, message: ExecutionError) -> None:
        self.notify(f"Error: {message.error}", severity="error")
        self._execution_services.pop(message.co_id, None)
        self._co_workers.pop(message.co_id, None)
        self._refresh_co_list()

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
                self.notify(f"Stopped: {co_id[:8]}")
                self._refresh_co_list()
                if co_id == self._selected_co_id:
                    self._show_co_detail(co_id)

    # ── Handle interaction panel decisions ──

    def on_interaction_panel_decision(self, message: InteractionPanel.Decision) -> None:
        if self._selected_co_id and self._selected_co_id in self._execution_services:
            exec_service = self._execution_services[self._selected_co_id]
            exec_service.provide_human_response(message.choice, message.text)
            self._awaiting_count = max(0, self._awaiting_count - 1)
            self._update_footer_awaiting()

    def on_tool_preview_approved(self, message: ToolPreview.Approved) -> None:
        if self._selected_co_id and self._selected_co_id in self._execution_services:
            exec_service = self._execution_services[self._selected_co_id]
            exec_service.provide_human_response("approve")

    def on_tool_preview_rejected(self, message: ToolPreview.Rejected) -> None:
        if self._selected_co_id and self._selected_co_id in self._execution_services:
            exec_service = self._execution_services[self._selected_co_id]
            exec_service.provide_human_response("reject", message.reason)

    def _update_footer_awaiting(self) -> None:
        if self._awaiting_count > 0:
            self.sub_title = f"Cognitive Operating System  |  {self._awaiting_count} awaiting"
        else:
            self.sub_title = "Cognitive Operating System"
