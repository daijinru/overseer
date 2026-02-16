"""Tool result screen — modal for viewing full tool output."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

MAX_CONTENT_LENGTH = 50000


class ToolResultScreen(ModalScreen):
    """Modal screen for viewing full tool result content."""

    BINDINGS = [
        ("escape", "dismiss_screen", "Close"),
        ("q", "dismiss_screen", "Close"),
    ]

    def __init__(self, tool_name: str, result: Dict[str, Any]) -> None:
        super().__init__()
        self._tool_name = tool_name
        self._result = result

    def compose(self) -> ComposeResult:
        with Vertical(id="tool-result-container"):
            yield Static(
                f"[bold]Tool Result: {self._tool_name}[/bold]",
                id="tool-result-title",
            )
            yield Static(self._format_status(), id="tool-result-status")
            with VerticalScroll(id="tool-result-scroll"):
                yield Static(self._format_content(), id="tool-result-content")
            yield Button("Close", id="tool-result-close", variant="primary")

    def _format_status(self) -> str:
        status = self._result.get("status", "unknown")
        if status == "ok":
            return "[green bold]Status: OK[/green bold]"
        elif status == "error":
            return "[red bold]Status: Error[/red bold]"
        elif status == "rejected":
            reason = self._result.get("reason", "")
            return f"[yellow bold]Status: Rejected[/yellow bold] {reason}"
        return f"[dim]Status: {status}[/dim]"

    def _format_content(self) -> str:
        content = (
            self._result.get("output")
            or self._result.get("content")
            or self._result.get("error")
            or ""
        )

        if not content:
            content = json.dumps(self._result, ensure_ascii=False, indent=2)

        if len(content) > MAX_CONTENT_LENGTH:
            content = content[:MAX_CONTENT_LENGTH] + "\n\n[dim][truncated][/dim]"

        try:
            parsed = json.loads(content)
            content = json.dumps(parsed, ensure_ascii=False, indent=2)
            return self._highlight_json(content)
        except (json.JSONDecodeError, TypeError):
            pass

        return content

    @staticmethod
    def _highlight_json(text: str) -> str:
        lines = []
        for line in text.split("\n"):
            stripped = line.strip()
            if ":" in stripped and not stripped.startswith(("{", "[", "}")):
                parts = line.split(":", 1)
                key = parts[0].rstrip()
                val = parts[1].lstrip() if len(parts) > 1 else ""
                lines.append(f"[bold cyan]{key}[/bold cyan]: [green]{val}[/green]")
            else:
                lines.append(f"[dim]{line}[/dim]")
        return "\n".join(lines)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "tool-result-close":
            self.dismiss(None)

    def action_dismiss_screen(self) -> None:
        self.dismiss(None)


class ToolResultListScreen(ModalScreen):
    """Modal for selecting which tool result to view when multiple exist."""

    BINDINGS = [("escape", "dismiss_screen", "Close")]

    def __init__(self, results: List[Dict[str, Any]]) -> None:
        super().__init__()
        self._results = results

    def compose(self) -> ComposeResult:
        with Vertical(id="tool-result-list-container"):
            yield Static("[bold]Tool Results[/bold]", id="tool-result-list-title")
            for i, r in enumerate(self._results):
                tool = r.get("tool", "?")
                status = r.get("status", "?")
                yield Button(
                    f"[{i + 1}] {tool}: {status}",
                    id=f"tool-result-item-{i}",
                    variant="primary" if status == "ok" else "error",
                )
            yield Button("Close", id="tool-result-list-close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "tool-result-list-close":
            self.dismiss(None)
        elif event.button.id and event.button.id.startswith("tool-result-item-"):
            idx = int(event.button.id.split("-")[-1])
            self.dismiss(self._results[idx])

    def action_dismiss_screen(self) -> None:
        self.dismiss(None)
