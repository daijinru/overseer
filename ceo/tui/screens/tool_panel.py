"""Tool panel screen — full-screen page for browsing registered MCP tools."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

logger = logging.getLogger(__name__)

PERMISSION_STYLES = {
    "auto": "[green]auto[/green]",
    "notify": "[yellow]notify[/yellow]",
    "confirm": "[bold yellow]confirm[/bold yellow]",
    "approve": "[bold red]approve[/bold red]",
}


class ToolListItem(ListItem):
    """A single tool entry in the list."""

    def __init__(self, tool_info: Dict[str, Any]) -> None:
        super().__init__(classes="item-card")
        self.tool_name = tool_info["name"]
        self._info = tool_info
        self._is_server = False

    def compose(self) -> ComposeResult:
        name = self._info["name"]
        source = self._info["source"]
        perm = self._info["permission"]

        if source == "builtin":
            source_label = "[dim]builtin[/dim]"
        else:
            source_label = f"[dim]mcp:{source}[/dim]"

        perm_label = PERMISSION_STYLES.get(perm, f"[dim]{perm}[/dim]")

        desc = self._info.get("description", "")
        preview = desc[:50] + "..." if len(desc) > 50 else desc
        preview = preview.replace("\n", " ")

        yield Label(
            f"[bold]{name}[/bold]  {source_label}  {perm_label}\n[dim]{preview}[/dim]",
            classes="item-label",
        )


class ServerListItem(ListItem):
    """An MCP server entry in the list (not a tool, but a server overview)."""

    def __init__(self, server_info: Dict[str, Any]) -> None:
        super().__init__(classes="item-card")
        self.tool_name = f"__server__{server_info['server_name']}"
        self._info = server_info
        self._is_server = True

    def compose(self) -> ComposeResult:
        name = self._info["server_name"]
        transport = self._info["transport"]
        tool_count = self._info.get("discovered_tools", 0)

        if tool_count > 0:
            status = f"[green]{tool_count} tools[/green]"
        else:
            status = "[dim]not connected[/dim]"

        if transport == "stdio":
            cmd = self._info.get("command", "")
            detail = f"{cmd} {' '.join(self._info.get('args', []))}"
        else:
            detail = self._info.get("url", "")
        preview = detail[:50] + "..." if len(detail) > 50 else detail

        yield Label(
            f"[bold reverse] {name} [/bold reverse]  "
            f"[dim]{transport}[/dim]  {status}\n"
            f"[dim]{preview}[/dim]",
            classes="item-label",
        )


class ToolPanelScreen(Screen):
    """Full-screen page for viewing registered tools."""

    BINDINGS = [
        ("j", "next_tool", "Next"),
        ("k", "prev_tool", "Prev"),
        ("c", "connect_mcp", "Connect"),
        ("y", "copy_tool", "Copy"),
        ("escape", "go_back", "Back"),
        ("q", "go_back", "Back"),
    ]

    def __init__(
        self,
        tools: List[Dict[str, Any]],
        servers: List[Dict[str, Any]] | None = None,
        tool_service: Optional[Any] = None,
    ) -> None:
        super().__init__()
        self._tools = tools
        self._servers = servers or []
        self._selected_name: str | None = None
        # A live ToolService from a running ExecutionService (already connected)
        self._live_tool_service = tool_service
        # A ToolService we create for on-demand connection (we own its lifecycle)
        self._owned_tool_service: Optional[Any] = None
        self._connecting = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="tool-panel-container"):
            with Vertical(id="tool-list-panel"):
                yield Static("Tools", classes="panel-title")
                yield Static("", id="tool-count-label", classes="filter-label")
                yield ListView(id="tool-listview")
            with Vertical(id="tool-detail-panel"):
                yield Static(
                    "[dim]Select a tool to view details[/dim]",
                    id="tool-detail-header",
                )
                with VerticalScroll(id="tool-detail-scroll"):
                    yield Static("", id="tool-detail-content")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_list()

    def _refresh_list(self) -> None:
        # Sort tools: builtin first, then group by MCP server name
        def sort_key(t: Dict[str, Any]) -> tuple:
            source = t["source"]
            if source == "builtin":
                return (0, "", t["name"])
            return (1, source, t["name"])

        self._tools.sort(key=sort_key)

        listview = self.query_one("#tool-listview", ListView)
        listview.clear()

        # Build set of servers that have discovered tools
        servers_with_tools = {t["source"] for t in self._tools if t["source"] != "builtin"}
        # Servers that have NO discovered tools (not connected yet)
        unconnected_servers = [
            s for s in self._servers
            if s["server_name"] not in servers_with_tools
        ]

        # Add builtin tools
        builtin_tools = [t for t in self._tools if t["source"] == "builtin"]
        if builtin_tools:
            for tool in builtin_tools:
                listview.append(ToolListItem(tool))

        # Add MCP tools grouped by server, with server headers
        current_server = None
        for tool in self._tools:
            if tool["source"] == "builtin":
                continue
            if tool["source"] != current_server:
                current_server = tool["source"]
                # Find server info for this source
                srv = next(
                    (s for s in self._servers if s["server_name"] == current_server),
                    None,
                )
                if srv:
                    listview.append(ServerListItem(srv))
            listview.append(ToolListItem(tool))

        # Append unconnected MCP servers at the end
        for srv in unconnected_servers:
            listview.append(ServerListItem(srv))

        # Count summary
        builtin_count = len(builtin_tools)
        mcp_count = len(self._tools) - builtin_count
        server_count = len(self._servers)
        self.query_one("#tool-count-label", Static).update(
            f"Tools: [bold]{len(self._tools)}[/bold]  "
            f"(builtin: {builtin_count}  mcp: {mcp_count})  "
            f"Servers: [bold]{server_count}[/bold]"
        )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, ToolListItem):
            self._selected_name = item.tool_name
            tool = next((t for t in self._tools if t["name"] == item.tool_name), None)
            self._show_detail(tool)
        elif isinstance(item, ServerListItem):
            self._selected_name = item.tool_name
            self._show_server_detail(item._info)

    def _show_server_detail(self, srv: Dict[str, Any]) -> None:
        header = self.query_one("#tool-detail-header", Static)
        content = self.query_one("#tool-detail-content", Static)

        name = srv["server_name"]
        transport = srv["transport"]
        tool_count = srv.get("discovered_tools", 0)

        if tool_count > 0:
            status = f"[green]Connected ({tool_count} tools discovered)[/green]"
        else:
            status = "[yellow]Not connected[/yellow] — start a CO to discover tools"

        header.update(
            f"[bold reverse] SERVER: {name} [/bold reverse]  "
            f"[dim]y: copy  q: back[/dim]"
        )

        lines = [
            f"[bold underline]Server:[/bold underline]     {name}",
            f"[bold underline]Transport:[/bold underline]  {transport}",
            f"[bold underline]Status:[/bold underline]     {status}",
        ]

        if transport == "stdio":
            cmd = srv.get("command", "")
            args = " ".join(srv.get("args", []))
            lines.append(f"\n[bold underline]Command:[/bold underline]\n  {cmd} {args}")
        else:
            url = srv.get("url", "")
            lines.append(f"\n[bold underline]URL:[/bold underline]\n  {url}")

        # Show tools belonging to this server
        server_tools = [t for t in self._tools if t["source"] == name]
        if server_tools:
            lines.append(f"\n[bold underline]Discovered Tools ({len(server_tools)}):[/bold underline]")
            for t in server_tools:
                perm = PERMISSION_STYLES.get(t["permission"], t["permission"])
                desc = t.get("description", "")
                short_desc = desc[:60] + "..." if len(desc) > 60 else desc
                lines.append(f"  [bold]{t['name']}[/bold]  {perm}")
                if short_desc:
                    lines.append(f"    [dim]{short_desc}[/dim]")

        content.update("\n".join(lines))

    def _show_detail(self, tool: Dict[str, Any] | None) -> None:
        header = self.query_one("#tool-detail-header", Static)
        content = self.query_one("#tool-detail-content", Static)

        if tool is None:
            header.update("[dim]Select a tool to view details[/dim]")
            content.update("")
            return

        name = tool["name"]
        source = tool["source"]
        perm = tool["permission"]
        desc = tool.get("description", "") or "No description"
        params = tool.get("parameters", {})

        perm_label = PERMISSION_STYLES.get(perm, perm)

        if source == "builtin":
            source_text = "[bold]builtin[/bold]"
        else:
            source_text = f"[bold]mcp:{source}[/bold]"

        header.update(
            f"[bold]{name}[/bold]  {source_text}  {perm_label}  "
            f"[dim]y: copy  q: back[/dim]"
        )

        # Format parameters schema
        params_text = self._format_params(params)

        detail_text = (
            f"[bold underline]Name:[/bold underline]        {name}\n"
            f"[bold underline]Source:[/bold underline]      {source_text}\n"
            f"[bold underline]Permission:[/bold underline]  {perm_label}\n"
            f"\n[bold underline]Description:[/bold underline]\n{desc}\n"
            f"\n[bold underline]Parameters:[/bold underline]\n{params_text}"
        )
        content.update(detail_text)

    def _format_params(self, params: Dict[str, Any]) -> str:
        if not params:
            return "[dim]No parameters[/dim]"

        properties = params.get("properties", {})
        required = set(params.get("required", []))

        if not properties:
            return "[dim]No parameters[/dim]"

        lines = []
        for prop_name, prop_info in properties.items():
            prop_type = prop_info.get("type", "any")
            prop_desc = prop_info.get("description", "")
            req_mark = " [bold red]*[/bold red]" if prop_name in required else ""

            lines.append(
                f"  [bold]{prop_name}[/bold]{req_mark}  "
                f"[dim]({prop_type})[/dim]"
            )
            if prop_desc:
                lines.append(f"    [dim]{prop_desc}[/dim]")

        if required:
            lines.append(f"\n[dim]* = required[/dim]")

        # Also show raw JSON schema for completeness
        try:
            raw = json.dumps(params, indent=2, ensure_ascii=False)
            lines.append(f"\n[bold underline]Raw Schema:[/bold underline]\n{raw}")
        except (TypeError, ValueError):
            pass

        return "\n".join(lines)

    # -- Navigation --

    def action_next_tool(self) -> None:
        listview = self.query_one("#tool-listview", ListView)
        if listview.index is None:
            if len(listview.children) > 0:
                listview.index = 0
        elif listview.index < len(listview.children) - 1:
            listview.index += 1
        self._emit_selected(listview)

    def action_prev_tool(self) -> None:
        listview = self.query_one("#tool-listview", ListView)
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
                if isinstance(item, ToolListItem):
                    self._selected_name = item.tool_name
                    tool = next(
                        (t for t in self._tools if t["name"] == item.tool_name),
                        None,
                    )
                    self._show_detail(tool)
                elif isinstance(item, ServerListItem):
                    self._selected_name = item.tool_name
                    self._show_server_detail(item._info)

    # -- Connect --

    def action_connect_mcp(self) -> None:
        """Connect to MCP servers to discover tools."""
        # Already have live data from a running ExecutionService
        if self._live_tool_service is not None:
            self.notify("Already connected via running event")
            return
        if self._connecting:
            self.notify("Connecting...", severity="warning")
            return
        if not self._servers:
            self.notify("No MCP servers configured", severity="warning")
            return

        self._connecting = True
        self.notify("Connecting to MCP servers...")
        self.run_worker(self._do_connect(), exclusive=True)

    async def _do_connect(self) -> None:
        from ceo.services.tool_service import ToolService

        ts = ToolService()
        try:
            await ts.connect()
            self._owned_tool_service = ts
            self._tools = ts.list_tools_detailed()
            self._servers = ts.list_configured_servers()
            self._refresh_list()
            self.notify(
                f"Connected — {len(self._tools)} tools discovered",
                severity="information",
            )
        except Exception as e:
            logger.error("MCP connect failed: %s", e)
            self.notify(f"Connect failed: {e}", severity="error")
        finally:
            self._connecting = False

    # -- Copy --

    def action_copy_tool(self) -> None:
        if self._selected_name is None:
            self.notify("No tool selected", severity="warning")
            return

        # Handle server items
        if self._selected_name.startswith("__server__"):
            server_name = self._selected_name[len("__server__"):]
            srv = next((s for s in self._servers if s["server_name"] == server_name), None)
            if srv is None:
                return
            text = (
                f"Server:    {srv['server_name']}\n"
                f"Transport: {srv['transport']}\n"
            )
            if srv["transport"] == "stdio":
                text += f"Command:   {srv.get('command', '')} {' '.join(srv.get('args', []))}\n"
            else:
                text += f"URL:       {srv.get('url', '')}\n"
        else:
            tool = next((t for t in self._tools if t["name"] == self._selected_name), None)
            if tool is None:
                return
            params_json = json.dumps(tool.get("parameters", {}), indent=2, ensure_ascii=False)
            text = (
                f"Name:       {tool['name']}\n"
                f"Source:     {tool['source']}\n"
                f"Permission: {tool['permission']}\n"
                f"Description:\n{tool.get('description', '')}\n"
                f"\nParameters:\n{params_json}"
            )

        from ceo.tui.widgets.execution_log import _copy_to_system_clipboard

        if _copy_to_system_clipboard(text):
            self.notify("Copied to clipboard")
        else:
            self.app.copy_to_clipboard(text)
            self.notify("Copied to clipboard (OSC 52)")

    # -- Back --

    def action_go_back(self) -> None:
        # Disconnect if we created our own connection
        if self._owned_tool_service is not None:
            self.run_worker(self._do_disconnect())
        else:
            self.app.pop_screen()

    async def _do_disconnect(self) -> None:
        if self._owned_tool_service is not None:
            try:
                await self._owned_tool_service.disconnect()
            except Exception as e:
                logger.debug("Error disconnecting: %s", e)
            self._owned_tool_service = None
        self.app.pop_screen()
