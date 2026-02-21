"""Tests for Perception features (Phase 1–3)."""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock

# Stub out optional 'mcp' dependency so ExecutionService can be imported
# without the actual MCP SDK installed.
if "mcp" not in sys.modules:
    _mcp_mock = MagicMock()
    for _sub in (
        "mcp", "mcp.client", "mcp.client.stdio", "mcp.client.sse",
        "mcp.client.streamable_http", "mcp.client.session_group",
        "mcp.types",
    ):
        sys.modules[_sub] = _mcp_mock

from retro_cogos.services.cognitive_object_service import CognitiveObjectService
from retro_cogos.services.context_service import ContextService
from retro_cogos.services.execution_service import ExecutionService
from retro_cogos.services.memory_service import MemoryService


# ── Phase 2: classify_tool_result ──


def test_classify_success(isolated_db):
    assert ContextService.classify_tool_result({"status": "ok", "output": "data"}) == "success"


def test_classify_error(isolated_db):
    assert ContextService.classify_tool_result({"status": "error", "error": "fail"}) == "error"


def test_classify_empty(isolated_db):
    assert ContextService.classify_tool_result({"status": "ok", "output": ""}) == "empty"


def test_classify_empty_whitespace(isolated_db):
    assert ContextService.classify_tool_result({"status": "ok", "output": "   "}) == "empty"


def test_classify_partial(isolated_db):
    assert ContextService.classify_tool_result({"status": "unknown"}) == "partial"


def test_classify_error_in_body(isolated_db):
    result = {"result": "something", "status": "error"}
    assert ContextService.classify_tool_result(result) == "error"


# ── Phase 2: merge_tool_result with classification & diff ──


def test_merge_first_call_no_diff(isolated_db):
    co_svc = CognitiveObjectService()
    ctx_svc = ContextService()

    co = co_svc.create("Test")
    ctx_svc.merge_tool_result(
        co, 1, "file_read", '{"status": "ok", "output": "hello"}',
        raw_result={"status": "ok", "output": "hello"},
    )

    co = co_svc.get(co.id)
    findings = co.context.get("accumulated_findings", [])
    assert len(findings) == 1
    value = findings[0]["value"]
    assert "[success]" in value
    assert "SAME" not in value
    assert "CHANGED" not in value


def test_merge_same_output(isolated_db):
    co_svc = CognitiveObjectService()
    ctx_svc = ContextService()

    co = co_svc.create("Test")
    result_str = '{"status": "ok", "output": "hello"}'
    raw = {"status": "ok", "output": "hello"}

    ctx_svc.merge_tool_result(co, 1, "file_read", result_str, raw_result=raw)
    ctx_svc.merge_tool_result(co, 2, "file_read", result_str, raw_result=raw)

    co = co_svc.get(co.id)
    findings = co.context.get("accumulated_findings", [])
    second_value = findings[1]["value"]
    assert "SAME" in second_value


def test_merge_changed_output(isolated_db):
    co_svc = CognitiveObjectService()
    ctx_svc = ContextService()

    co = co_svc.create("Test")
    raw = {"status": "ok", "output": "hello"}

    ctx_svc.merge_tool_result(co, 1, "file_read", "result_a", raw_result=raw)
    ctx_svc.merge_tool_result(co, 2, "file_read", "result_b", raw_result=raw)

    co = co_svc.get(co.id)
    findings = co.context.get("accumulated_findings", [])
    second_value = findings[1]["value"]
    assert "CHANGED" in second_value


def test_merge_classification_prefix(isolated_db):
    co_svc = CognitiveObjectService()
    ctx_svc = ContextService()

    co = co_svc.create("Test")
    ctx_svc.merge_tool_result(
        co, 1, "web_search", "error output",
        raw_result={"status": "error", "error": "timeout"},
    )

    co = co_svc.get(co.id)
    findings = co.context.get("accumulated_findings", [])
    assert "[error]" in findings[0]["value"]


def test_merge_diff_key_includes_args(isolated_db):
    """Different args for the same tool should NOT produce a diff annotation."""
    co_svc = CognitiveObjectService()
    ctx_svc = ContextService()

    co = co_svc.create("Test")
    raw = {"status": "ok", "output": "content_a"}
    ctx_svc.merge_tool_result(
        co, 1, "file_read", "content_a", raw_result=raw,
        tool_args={"path": "a.txt"},
    )
    raw_b = {"status": "ok", "output": "content_b"}
    ctx_svc.merge_tool_result(
        co, 2, "file_read", "content_b", raw_result=raw_b,
        tool_args={"path": "b.txt"},
    )

    co = co_svc.get(co.id)
    findings = co.context.get("accumulated_findings", [])
    second_value = findings[1]["value"]
    # Different args → no diff comparison should be made
    assert "SAME" not in second_value
    assert "CHANGED" not in second_value


# ── Phase 2: check_intent_deviation ──


def test_deviation_all_errors(isolated_db):
    ctx_svc = ContextService()
    results = [
        {"status": "error", "tool": "web_search"},
        {"status": "error", "tool": "file_read"},
    ]
    d = ctx_svc.check_intent_deviation("find revenue data", results)
    assert d is not None
    assert "failed" in d


def test_deviation_all_empty(isolated_db):
    ctx_svc = ContextService()
    results = [
        {"status": "ok", "output": ""},
        {"status": "ok", "output": "  "},
    ]
    d = ctx_svc.check_intent_deviation("find revenue data", results)
    assert d is not None
    assert "empty" in d


def test_deviation_no_deviation(isolated_db):
    ctx_svc = ContextService()
    results = [
        {"status": "ok", "output": "revenue is 1M"},
        {"status": "ok", "output": "profit is 200k"},
    ]
    d = ctx_svc.check_intent_deviation("find revenue data", results)
    assert d is None


def test_deviation_no_intent(isolated_db):
    ctx_svc = ContextService()
    results = [{"status": "error"}]
    d = ctx_svc.check_intent_deviation("", results)
    assert d is None


def test_deviation_empty_results(isolated_db):
    ctx_svc = ContextService()
    d = ctx_svc.check_intent_deviation("find data", [])
    assert d is None


def test_deviation_partial_failure(isolated_db):
    ctx_svc = ContextService()
    results = [
        {"status": "error", "tool": "web_search"},
        {"status": "ok", "output": "some data", "tool": "file_read"},
    ]
    d = ctx_svc.check_intent_deviation("find revenue data", results)
    assert d is not None
    assert "1/2" in d
    assert "web_search" in d


# ── Phase 1: _detect_no_progress ──


def test_no_progress_chinese(isolated_db):
    svc = ExecutionService()
    assert svc._detect_no_progress("目前没有进展，需要换一种方式") is True


def test_no_progress_english(isolated_db):
    svc = ExecutionService()
    assert svc._detect_no_progress("We seem to be stuck on this problem") is True


def test_no_progress_negative(isolated_db):
    svc = ExecutionService()
    assert svc._detect_no_progress("Good progress on the analysis so far") is False


# ── Phase 3: _record_approval + _build_approval_summary ──


def test_record_approve(isolated_db):
    svc = ExecutionService()
    svc._record_approval("file_write", True)

    assert svc._approval_stats["file_write"]["approve"] == 1
    assert svc._approval_stats["file_write"]["reject"] == 0
    assert svc._consecutive_rejects.get("file_write", 0) == 0


def test_record_reject(isolated_db):
    svc = ExecutionService()
    svc._record_approval("file_write", False)
    svc._record_approval("file_write", False)

    assert svc._approval_stats["file_write"]["reject"] == 2
    assert svc._consecutive_rejects["file_write"] == 2


def test_record_reject_reset_on_approve(isolated_db):
    svc = ExecutionService()
    svc._record_approval("file_write", False)
    svc._record_approval("file_write", False)
    assert svc._consecutive_rejects["file_write"] == 2

    svc._record_approval("file_write", True)
    assert svc._consecutive_rejects["file_write"] == 0


def test_summary_insufficient_data(isolated_db):
    svc = ExecutionService()
    svc._record_approval("file_write", True)  # only 1 data point
    summary = svc._build_approval_summary()
    assert summary == []


def test_summary_with_data(isolated_db):
    svc = ExecutionService()
    for _ in range(5):
        svc._record_approval("file_write", True)
    for _ in range(2):
        svc._record_approval("file_write", False)

    summary = svc._build_approval_summary()
    assert len(summary) == 1
    assert summary[0]["tool"] == "file_write"
    assert summary[0]["approve"] == 5
    assert summary[0]["reject"] == 2
    assert summary[0]["reject_rate"] == round(2 / 7, 2)


# ── Phase 3: _check_auto_escalate ──


def test_escalate_below_threshold(isolated_db):
    svc = ExecutionService()
    svc.tool_service = MagicMock()

    svc._consecutive_rejects["file_delete"] = 2
    svc._check_auto_escalate("file_delete", "test-co-id")

    svc.tool_service.override_permission.assert_not_called()


def test_escalate_at_threshold(isolated_db):
    svc = ExecutionService()
    svc.tool_service = MagicMock()

    svc._consecutive_rejects["file_delete"] = 3
    svc._check_auto_escalate("file_delete", "test-co-id")

    svc.tool_service.override_permission.assert_called_once_with("file_delete", "approve")
    assert svc._consecutive_rejects["file_delete"] == 0


# ── Phase 3: _persist_preferences ──


def test_persist_high_reject_rate(isolated_db):
    svc = ExecutionService()
    co = svc.co_service.create("Persist test")
    # 8 rejects, 2 approves → 80% reject rate
    svc._approval_stats["dangerous_tool"] = {"approve": 2, "reject": 8}
    svc._persist_preferences(co.id)

    memories = svc.memory_service.retrieve("preference dangerous_tool", limit=5)
    assert len(memories) == 1
    assert "reject" in memories[0].content.lower()
    assert "dangerous_tool" in memories[0].content


def test_persist_high_approve_rate(isolated_db):
    svc = ExecutionService()
    co = svc.co_service.create("Persist test")
    # 10 approves, 0 rejects → 0% reject rate, n=10 >= 5
    svc._approval_stats["safe_tool"] = {"approve": 10, "reject": 0}
    svc._persist_preferences(co.id)

    memories = svc.memory_service.retrieve("preference safe_tool", limit=5)
    assert len(memories) == 1
    assert "approve" in memories[0].content.lower()


def test_persist_insufficient_data(isolated_db):
    svc = ExecutionService()
    co = svc.co_service.create("Persist test")
    svc._approval_stats["rare_tool"] = {"approve": 1, "reject": 1}
    svc._persist_preferences(co.id)

    memories = svc.memory_service.list_all()
    assert len(memories) == 0


def test_persist_no_duplicate(isolated_db):
    svc = ExecutionService()
    co = svc.co_service.create("Persist test")
    svc._approval_stats["dangerous_tool"] = {"approve": 1, "reject": 9}

    svc._persist_preferences(co.id)
    svc._persist_preferences(co.id)  # second call should be deduped

    memories = svc.memory_service.retrieve("preference dangerous_tool", limit=10)
    assert len(memories) == 1
