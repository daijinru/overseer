"""Tool service — MCP tool management and permission control."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from mcp import ClientSessionGroup, StdioServerParameters
from mcp.client.session_group import SseServerParameters, StreamableHttpParameters

from ceo.config import MCPServerConfig, get_config
from ceo.core.enums import ToolPermission
from ceo.core.protocols import ToolCall

logger = logging.getLogger(__name__)


# Built-in tool implementations for when MCP server is not available
BUILTIN_TOOLS = {
    "file_read": {
        "name": "file_read",
        "description": "Read contents of a file",
        "parameters": {"path": "string"},
    },
    "file_write": {
        "name": "file_write",
        "description": "Write contents to a file",
        "parameters": {"path": "string", "content": "string"},
    },
    "file_list": {
        "name": "file_list",
        "description": "List files in a directory",
        "parameters": {"path": "string"},
    },
}


def _build_server_params(
    cfg: MCPServerConfig,
) -> StdioServerParameters | SseServerParameters | StreamableHttpParameters:
    """Convert config to MCP transport parameters."""
    if cfg.transport == "stdio":
        if not cfg.command:
            raise ValueError("stdio transport requires 'command'")
        return StdioServerParameters(
            command=cfg.command,
            args=cfg.args,
            env=cfg.env,
        )
    elif cfg.transport == "sse":
        if not cfg.url:
            raise ValueError("sse transport requires 'url'")
        return SseServerParameters(
            url=cfg.url,
            headers=cfg.headers or {},
        )
    elif cfg.transport == "streamable_http":
        if not cfg.url:
            raise ValueError("streamable_http transport requires 'url'")
        return StreamableHttpParameters(
            url=cfg.url,
            headers=cfg.headers or {},
        )
    else:
        raise ValueError(f"Unknown transport: {cfg.transport}")


class ToolService:
    def __init__(self):
        self._cfg = get_config()
        self._tools: Dict[str, Dict[str, Any]] = dict(BUILTIN_TOOLS)
        # MCP session group manages multiple MCP server connections
        self._session_group: Optional[ClientSessionGroup] = None
        # Map: tool_name -> mcp server name, for routing calls
        self._mcp_tool_map: Dict[str, str] = {}
        self._connected = False

    async def connect(self) -> None:
        """Connect to all configured MCP servers and discover tools."""
        mcp_servers = self._cfg.mcp.servers
        if not mcp_servers:
            logger.info("No MCP servers configured, using builtin tools only")
            return

        self._session_group = ClientSessionGroup()
        await self._session_group.__aenter__()

        for name, server_cfg in mcp_servers.items():
            try:
                params = _build_server_params(server_cfg)
                session = await self._session_group.connect_to_server(params)
                logger.info("Connected to MCP server: %s", name)

                # Discover tools from this server
                result = await session.list_tools()
                for tool in result.tools:
                    tool_info = {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": tool.inputSchema or {},
                    }
                    self._tools[tool.name] = tool_info
                    self._mcp_tool_map[tool.name] = name
                    logger.info("  Discovered tool: %s", tool.name)

            except Exception as e:
                logger.error("Failed to connect to MCP server '%s': %s", name, e)

        self._connected = True

    async def disconnect(self) -> None:
        """Disconnect from all MCP servers."""
        if self._session_group:
            try:
                await self._session_group.__aexit__(None, None, None)
            except Exception as e:
                logger.warning("Error closing MCP session group: %s", e)
            self._session_group = None
            self._mcp_tool_map.clear()
            # Remove MCP tools, keep builtins
            self._tools = dict(BUILTIN_TOOLS)
            self._connected = False
            logger.info("Disconnected from all MCP servers")

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return list of available tools."""
        return list(self._tools.values())

    def filter_args(self, tool_name: str, args: Dict[str, Any]) -> tuple[Dict[str, Any], List[str]]:
        """Filter tool args to only include parameters defined in the schema.

        Returns (filtered_args, removed_keys).
        """
        schema = self._tools.get(tool_name, {}).get("parameters", {})
        valid_props = schema.get("properties", {})
        if not valid_props:
            return args, []
        filtered = {k: v for k, v in args.items() if k in valid_props}
        removed = [k for k in args if k not in valid_props]
        return filtered, removed

    def get_permission(self, tool_name: str) -> ToolPermission:
        """Get permission level for a tool."""
        perms = self._cfg.tool_permissions
        # Check tool-specific permission first
        if tool_name in perms:
            level = perms[tool_name]
        elif tool_name in self._mcp_tool_map:
            # MCP tools default to auto (read-only queries) unless explicitly configured
            level = perms.get("mcp_default", "auto")
        else:
            level = perms.get("default", "confirm")
        try:
            return ToolPermission(level)
        except ValueError:
            return ToolPermission.CONFIRM

    def needs_human_approval(self, tool_name: str) -> bool:
        """Check if a tool call requires human approval before execution."""
        perm = self.get_permission(tool_name)
        return perm in (ToolPermission.CONFIRM, ToolPermission.APPROVE)

    def needs_preview(self, tool_name: str) -> bool:
        """Check if a tool call should show a preview before approval."""
        return self.get_permission(tool_name) == ToolPermission.APPROVE

    async def execute(self, tool_call: ToolCall) -> Dict[str, Any]:
        """Execute a tool call and return the result."""
        tool_name = tool_call.tool
        args = tool_call.args

        logger.info("Executing tool: %s with args: %s", tool_name, args)

        # Route to MCP server if the tool was discovered from one
        if tool_name in self._mcp_tool_map and self._session_group:
            args, removed = self.filter_args(tool_name, args)
            if removed:
                logger.info("Filtered args for %s: removed %s", tool_name, removed)
            return await self._execute_mcp(tool_name, args)

        # Fall back to builtin implementations
        try:
            if tool_name == "file_read":
                return await self._file_read(args)
            elif tool_name == "file_write":
                return await self._file_write(args)
            elif tool_name == "file_list":
                return await self._file_list(args)
            else:
                return {"status": "error", "error": f"Unknown tool: {tool_name}"}
        except Exception as e:
            logger.error("Tool execution failed: %s — %s", tool_name, e)
            return {"status": "error", "error": str(e)}

    async def _execute_mcp(
        self, tool_name: str, args: Dict[str, Any], max_retries: int = 3
    ) -> Dict[str, Any]:
        """Execute a tool via MCP server, with automatic retries on failure."""
        last_error = ""
        for attempt in range(1, max_retries + 1):
            try:
                result = await self._session_group.call_tool(tool_name, args)

                if result.isError:
                    error_text = ""
                    for block in result.content:
                        if hasattr(block, "text"):
                            error_text += block.text
                    last_error = error_text or "MCP tool error"
                    logger.warning(
                        "MCP tool '%s' returned error (attempt %d/%d): %s",
                        tool_name, attempt, max_retries, last_error,
                    )
                    if attempt < max_retries:
                        await asyncio.sleep(1.0 * attempt)
                        continue
                    return {"status": "error", "error": last_error}

                # Collect text content from result
                output_parts = []
                for block in result.content:
                    if hasattr(block, "text"):
                        output_parts.append(block.text)
                    elif hasattr(block, "data"):
                        output_parts.append(f"[binary data: {block.mimeType}]")

                return {"status": "ok", "output": "\n".join(output_parts)}

            except Exception as e:
                last_error = str(e)
                logger.warning(
                    "MCP tool '%s' execution failed (attempt %d/%d): %s",
                    tool_name, attempt, max_retries, e,
                )
                if attempt < max_retries:
                    await asyncio.sleep(1.0 * attempt)
                    continue

        logger.error("MCP tool '%s' failed after %d attempts: %s", tool_name, max_retries, last_error)
        return {"status": "error", "error": f"Failed after {max_retries} attempts: {last_error}"}

    # ── Builtin tool implementations ──

    async def _file_read(self, args: Dict[str, Any]) -> Dict[str, Any]:
        path = args.get("path", "")
        if not path:
            return {"status": "error", "error": "No path specified"}
        try:
            from pathlib import Path
            content = Path(path).read_text(encoding="utf-8")
            return {"status": "ok", "content": content[:10000]}
        except FileNotFoundError:
            return {"status": "error", "error": f"File not found: {path}"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _file_write(self, args: Dict[str, Any]) -> Dict[str, Any]:
        path = args.get("path", "")
        content = args.get("content", "")
        if not path:
            return {"status": "error", "error": "No path specified"}
        try:
            from pathlib import Path
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return {"status": "ok", "path": str(p.resolve()), "bytes_written": len(content)}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _file_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        path = args.get("path", ".")
        try:
            from pathlib import Path
            p = Path(path)
            if not p.is_dir():
                return {"status": "error", "error": f"Not a directory: {path}"}
            files = [str(f.name) for f in sorted(p.iterdir())]
            return {"status": "ok", "files": files}
        except Exception as e:
            return {"status": "error", "error": str(e)}
