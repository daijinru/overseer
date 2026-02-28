"""Tool service — MCP tool management and permission control."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import mcp as _mcp_module
from mcp import ClientSessionGroup, StdioServerParameters
from mcp.client.session_group import SseServerParameters, StreamableHttpParameters

from retro_cogos.config import MCPServerConfig, get_config
from retro_cogos.core.protocols import ToolCall

logger = logging.getLogger(__name__)


class _StderrPipe:
    """Captures MCP subprocess stderr via a real OS pipe.

    subprocess.Popen requires a real file descriptor for stderr redirection.
    This class creates an os.pipe() and reads from it in a background thread,
    buffering lines so they can be drained by the TUI later.
    """

    def __init__(self) -> None:
        self._read_fd, self._write_fd = os.pipe()
        # Wrap write end as a Python file object (keep fd ownership manual)
        self._write_file = os.fdopen(self._write_fd, "w", closefd=False)
        self._lines: List[str] = []
        self._lock = threading.Lock()
        self._stop = False
        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True
        )
        self._reader_thread.start()

    def _reader_loop(self) -> None:
        """Background thread that reads lines from the pipe read end."""
        try:
            with os.fdopen(self._read_fd, "r", closefd=True) as f:
                for raw_line in f:
                    stripped = raw_line.strip()
                    if stripped:
                        with self._lock:
                            self._lines.append(stripped)
                    if self._stop:
                        break
        except (OSError, ValueError):
            pass

    @property
    def write_file(self):
        """The writable file object with a real fileno()."""
        return self._write_file

    def drain_lines(self) -> List[str]:
        """Return and clear all buffered lines."""
        with self._lock:
            lines = list(self._lines)
            self._lines.clear()
        return lines

    def close(self) -> None:
        """Shut down the pipe and reader thread."""
        self._stop = True
        try:
            self._write_file.close()
        except OSError:
            pass
        try:
            os.close(self._write_fd)
        except OSError:
            pass
        self._reader_thread.join(timeout=2.0)


# Built-in tool implementations for when MCP server is not available
BUILTIN_TOOLS = {
    "file_read": {
        "name": "file_read",
        "description": "Read contents of a file",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"},
            },
            "required": ["path"],
        },
    },
    "file_write": {
        "name": "file_write",
        "description": "Write contents to a file. Relative paths are resolved against the configured output directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to write (relative paths resolve to output directory)"},
                "content": {"type": "string", "description": "Text content to write"},
            },
            "required": ["path", "content"],
        },
    },
    "file_list": {
        "name": "file_list",
        "description": "List files in a directory",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path to list"},
            },
            "required": ["path"],
        },
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
        # OS pipe that captures MCP subprocess stderr for their full lifetime
        self._stderr_pipe: Optional[_StderrPipe] = None
        # Phase 3: Runtime permission overrides (set by ExecutionService on auto-escalation)
        self._permission_overrides: Dict[str, str] = {}

    async def connect(self) -> List[str]:
        """Connect to all configured MCP servers and discover tools.

        Returns a list of log lines captured from MCP server stderr
        (e.g. startup messages).
        """
        mcp_servers = self._cfg.mcp.servers
        if not mcp_servers:
            logger.info("No MCP servers configured, using builtin tools only")
            return []

        self._session_group = ClientSessionGroup()
        await self._session_group.__aenter__()

        # Create an OS pipe to capture subprocess stderr for the full
        # lifetime of the MCP connections (not just startup).
        self._stderr_pipe = _StderrPipe()
        errlog = self._stderr_pipe.write_file

        # Monkey-patch mcp.stdio_client so that ClientSessionGroup's
        # internal call passes our errlog to the subprocess.
        # The default `errlog=sys.stderr` is bound at *import time*,
        # so swapping sys.stderr at call time has no effect.
        _original_stdio_client = _mcp_module.stdio_client

        @asynccontextmanager
        async def _patched_stdio_client(server, _errlog=None):
            async with _original_stdio_client(server, errlog=errlog) as streams:
                yield streams

        _mcp_module.stdio_client = _patched_stdio_client

        try:
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
        finally:
            # Restore original stdio_client
            _mcp_module.stdio_client = _original_stdio_client

        self._connected = True
        # Drain startup lines collected so far
        return self._stderr_pipe.drain_lines()

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
        if self._stderr_pipe is not None:
            self._stderr_pipe.close()
            self._stderr_pipe = None

    def drain_stderr(self) -> List[str]:
        """Return any new stderr lines from MCP subprocesses since last drain."""
        if self._stderr_pipe is not None:
            return self._stderr_pipe.drain_lines()
        return []

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return list of available tools."""
        return list(self._tools.values())

    def list_tools_detailed(self) -> List[Dict[str, Any]]:
        """Return all tools with source info.

        Permission display is informational only — security decisions are made
        by the kernel's FirewallEngine/PolicyStore.
        """
        result = []
        for name, info in self._tools.items():
            source = self._mcp_tool_map.get(name)
            result.append({
                "name": name,
                "description": info.get("description", ""),
                "parameters": info.get("parameters", {}),
                "source": source or "builtin",
                "permission": self._get_display_permission(name),
            })
        return result

    def _get_display_permission(self, tool_name: str) -> str:
        """Get permission level for display purposes (TUI panel).

        NOT used for security decisions — those go through FirewallEngine.
        """
        # Phase 3: Runtime overrides take precedence
        if tool_name in self._permission_overrides:
            return self._permission_overrides.get(tool_name, "confirm")
        perms = self._cfg.tool_permissions
        if tool_name in perms:
            level = perms[tool_name]
        elif tool_name in self._mcp_tool_map:
            level = perms.get("mcp_default", "auto")
        else:
            level = perms.get("default", "confirm")
        return level

    def list_configured_servers(self) -> List[Dict[str, Any]]:
        """Return MCP server configs without connecting."""
        servers = []
        for name, cfg in self._cfg.mcp.servers.items():
            info: Dict[str, Any] = {
                "server_name": name,
                "transport": cfg.transport,
            }
            if cfg.transport == "stdio":
                info["command"] = cfg.command or ""
                info["args"] = cfg.args
            else:
                info["url"] = cfg.url or ""
            # Count discovered tools for this server (if connected)
            tool_count = sum(1 for s in self._mcp_tool_map.values() if s == name)
            info["discovered_tools"] = tool_count
            servers.append(info)
        return servers

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

    def get_tool_schema(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Return the parameter schema for a tool, or None."""
        tool = self._tools.get(tool_name)
        return tool.get("parameters") if tool else None

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
        """Execute a tool via MCP server, with automatic retries on failure.

        Note: path sandboxing is now handled by FirewallEngine.sandbox_args()
        in the orchestration layer before this method is called.
        """
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
            # LLM sometimes omits path or uses a non-schema parameter name
            # that gets stripped by filter_args.  Auto-generate a timestamped
            # filename so the write doesn't silently fail.
            if content:
                import datetime as _dt
                ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
                path = f"output/auto_{ts}.md"
            else:
                return {"status": "error", "error": "No path specified"}
        try:
            from pathlib import Path
            output_dir = Path(self._cfg.context.output_dir)
            p = Path(path)
            # Always resolve into output_dir — use only the filename
            p = output_dir / p.name
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
