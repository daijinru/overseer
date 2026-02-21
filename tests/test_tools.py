"""Tests for tool service — Phase 5 verification."""

import pytest

from retro_cogos.core.enums import ToolPermission
from retro_cogos.core.protocols import ToolCall
from retro_cogos.services.tool_service import ToolService


def test_list_tools(isolated_db):
    svc = ToolService()
    tools = svc.list_tools()
    assert len(tools) >= 3
    names = [t["name"] for t in tools]
    assert "file_read" in names
    assert "file_write" in names
    assert "file_list" in names


def test_get_permission_configured(isolated_db):
    svc = ToolService()
    # file_read is configured as auto in config.yaml fixture
    perm = svc.get_permission("file_read")
    assert perm == ToolPermission.AUTO


def test_get_permission_default(isolated_db):
    svc = ToolService()
    perm = svc.get_permission("unknown_tool")
    assert perm == ToolPermission.CONFIRM


def test_needs_human_approval(isolated_db):
    svc = ToolService()
    assert svc.needs_human_approval("file_read") is False  # auto
    assert svc.needs_human_approval("file_write") is True  # confirm
    assert svc.needs_human_approval("unknown") is True  # default confirm


@pytest.mark.asyncio
async def test_file_write_and_read(isolated_db, tmp_path):
    svc = ToolService()

    # Write a file
    write_result = await svc.execute(
        ToolCall(tool="file_write", args={"path": str(tmp_path / "test.txt"), "content": "hello world"})
    )
    assert write_result["status"] == "ok"

    # Read it back
    read_result = await svc.execute(
        ToolCall(tool="file_read", args={"path": str(tmp_path / "test.txt")})
    )
    assert read_result["status"] == "ok"
    assert read_result["content"] == "hello world"


@pytest.mark.asyncio
async def test_file_list(isolated_db, tmp_path):
    svc = ToolService()

    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")

    result = await svc.execute(
        ToolCall(tool="file_list", args={"path": str(tmp_path)})
    )
    assert result["status"] == "ok"
    assert "a.txt" in result["files"]
    assert "b.txt" in result["files"]


@pytest.mark.asyncio
async def test_file_read_not_found(isolated_db):
    svc = ToolService()
    result = await svc.execute(
        ToolCall(tool="file_read", args={"path": "/nonexistent/path/file.txt"})
    )
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_unknown_tool(isolated_db):
    svc = ToolService()
    result = await svc.execute(
        ToolCall(tool="nonexistent_tool", args={})
    )
    assert result["status"] == "error"
