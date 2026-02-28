"""Artifact viewer screens — list + preview modals for CO artifacts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import List

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from overseer.models.artifact import Artifact

MAX_CONTENT_LENGTH = 50000

# Text file extensions we can preview in-TUI
_TEXT_EXTENSIONS = frozenset({
    ".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".toml",
    ".py", ".js", ".ts", ".html", ".css", ".xml", ".log",
    ".ini", ".cfg", ".conf", ".sh", ".sql", ".tsv",
})


def _is_text_file(path: Path) -> bool:
    return path.suffix.lower() in _TEXT_EXTENSIONS


def _open_with_system(path: str) -> None:
    """Open a file with the system default application."""
    p = Path(path)
    if not p.exists():
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    elif sys.platform == "win32":
        subprocess.Popen(["start", str(p)], shell=True)
    else:
        subprocess.Popen(["xdg-open", str(p)])


class ArtifactPreviewScreen(ModalScreen):
    """Modal screen for previewing a single artifact file."""

    BINDINGS = [
        ("escape", "dismiss_screen", "Close"),
        ("q", "dismiss_screen", "Close"),
        ("y", "copy_content", "Copy"),
        ("o", "open_file", "Open"),
    ]

    def __init__(self, artifact: Artifact) -> None:
        super().__init__()
        self._artifact = artifact
        self._raw_content = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="artifact-preview-container"):
            type_badge = f"[dim]{self._artifact.artifact_type}[/dim]" if self._artifact.artifact_type else ""
            yield Static(
                f"[bold]{self._artifact.name}[/bold]  {type_badge}  "
                f"[dim]y: copy  o: open  q: close[/dim]",
                id="artifact-preview-title",
            )
            yield Static(
                f"[dim]{self._artifact.file_path}[/dim]",
                id="artifact-preview-path",
            )
            with VerticalScroll(id="artifact-preview-scroll"):
                yield Static(self._load_content(), id="artifact-preview-content")
            with Horizontal(id="artifact-preview-buttons"):
                yield Button("Open File", id="artifact-btn-open", variant="primary")
                yield Button("Close", id="artifact-btn-close")

    def _load_content(self) -> str:
        p = Path(self._artifact.file_path)
        if not p.exists():
            self._raw_content = ""
            return f"[bold reverse]File not found:[/bold reverse] {p}"
        if not _is_text_file(p):
            size = p.stat().st_size
            self._raw_content = ""
            return (
                f"[dim]Binary file — cannot preview in terminal[/dim]\n"
                f"Size: {size:,} bytes\n"
                f"Press [bold]o[/bold] or click [bold]Open File[/bold] to view."
            )
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            self._raw_content = content
            if len(content) > MAX_CONTENT_LENGTH:
                content = content[:MAX_CONTENT_LENGTH] + "\n\n[dim][truncated][/dim]"
            return content
        except Exception as exc:
            self._raw_content = ""
            return f"[bold reverse]Error reading file:[/bold reverse] {exc}"

    def action_copy_content(self) -> None:
        from overseer.tui.widgets.execution_log import _copy_to_system_clipboard

        if not self._raw_content:
            self.notify("No text content to copy", severity="warning")
            return
        if _copy_to_system_clipboard(self._raw_content):
            self.notify("Content copied to clipboard")
        else:
            self.app.copy_to_clipboard(self._raw_content)
            self.notify("Content copied to clipboard (OSC 52)")

    def action_open_file(self) -> None:
        p = Path(self._artifact.file_path)
        if not p.exists():
            self.notify("File not found", severity="error")
            return
        _open_with_system(str(p))
        self.notify(f"Opened: {p.name}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "artifact-btn-close":
            self.dismiss(None)
        elif event.button.id == "artifact-btn-open":
            self.action_open_file()

    def action_dismiss_screen(self) -> None:
        self.dismiss(None)


class ArtifactListScreen(ModalScreen):
    """Modal for listing all artifacts of a CO."""

    BINDINGS = [("escape", "dismiss_screen", "Close")]

    def __init__(self, artifacts: List[Artifact]) -> None:
        super().__init__()
        self._artifacts = artifacts

    def compose(self) -> ComposeResult:
        with Vertical(id="artifact-list-container"):
            yield Static(
                f"[bold]Artifacts[/bold]  [dim]({len(self._artifacts)} items)[/dim]",
                id="artifact-list-title",
            )
            if not self._artifacts:
                yield Static("[dim]No artifacts[/dim]", classes="empty-state")
            else:
                for i, art in enumerate(self._artifacts):
                    type_badge = f"({art.artifact_type})" if art.artifact_type else ""
                    with Horizontal(classes="artifact-item-row"):
                        yield Button(
                            f"[{i + 1}] {art.name} {type_badge}",
                            id=f"artifact-preview-{i}",
                            variant="primary",
                            classes="artifact-item-btn",
                        )
                        yield Button(
                            "Open",
                            id=f"artifact-open-{i}",
                            classes="artifact-open-btn",
                        )
            yield Button("Close", id="artifact-list-close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "artifact-list-close":
            self.dismiss(None)
        elif bid.startswith("artifact-preview-"):
            idx = int(bid.split("-")[-1])
            artifact = self._artifacts[idx]
            self.app.push_screen(ArtifactPreviewScreen(artifact))
        elif bid.startswith("artifact-open-"):
            idx = int(bid.split("-")[-1])
            artifact = self._artifacts[idx]
            p = Path(artifact.file_path)
            if not p.exists():
                self.notify("File not found", severity="error")
                return
            _open_with_system(str(p))
            self.notify(f"Opened: {p.name}")

    def action_dismiss_screen(self) -> None:
        self.dismiss(None)
