"""Tests for Perception features (Phase 1–3).

After Milestone 1 refactoring, perception logic lives in:
- PerceptionBus (kernel/perception_bus.py): recording + classification + statistics
- FirewallEngine (kernel/firewall_engine.py): security judgements based on stats
- ContextService: still has classify/merge for backward compat (thin wrappers ok)
- ExecutionService: orchestration only, no direct perception methods

Tests are updated to target the new kernel components directly.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

# Stub out optional 'mcp' dependency so services can be imported
# without the actual MCP SDK installed.
if "mcp" not in sys.modules:
    _mcp_mock = MagicMock()
    for _sub in (
        "mcp", "mcp.client", "mcp.client.stdio", "mcp.client.sse",
        "mcp.client.streamable_http", "mcp.client.session_group",
        "mcp.types",
    ):
        sys.modules[_sub] = _mcp_mock

from overseer.kernel.perception_bus import PerceptionBus
from overseer.kernel.firewall_engine import FirewallEngine
from overseer.services.cognitive_object_service import CognitiveObjectService
from overseer.services.context_service import ContextService
from overseer.services.execution_service import ExecutionService
from overseer.services.memory_service import MemoryService
from overseer.config import get_config


# ── Phase 2: classify_tool_result (now on PerceptionBus + ContextService) ──


def test_classify_success(isolated_db):
    assert PerceptionBus.classify_result("test", {"status": "ok", "output": "data"}) == "success"
    # ContextService static method still works for backward compat
    assert ContextService.classify_tool_result({"status": "ok", "output": "data"}) == "success"


def test_classify_error(isolated_db):
    assert PerceptionBus.classify_result("test", {"status": "error", "error": "fail"}) == "error"
    assert ContextService.classify_tool_result({"status": "error", "error": "fail"}) == "error"


def test_classify_empty(isolated_db):
    assert PerceptionBus.classify_result("test", {"status": "ok", "output": ""}) == "empty"
    assert ContextService.classify_tool_result({"status": "ok", "output": ""}) == "empty"


def test_classify_empty_whitespace(isolated_db):
    assert PerceptionBus.classify_result("test", {"status": "ok", "output": "   "}) == "empty"
    assert ContextService.classify_tool_result({"status": "ok", "output": "   "}) == "empty"


def test_classify_partial(isolated_db):
    assert PerceptionBus.classify_result("test", {"status": "unknown"}) == "partial"
    assert ContextService.classify_tool_result({"status": "unknown"}) == "partial"


def test_classify_error_in_body(isolated_db):
    result = {"result": "something", "status": "error"}
    assert PerceptionBus.classify_result("test", result) == "error"
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


# ── Phase 2: check_intent_deviation (now also on FirewallEngine) ──


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


# ── Phase 1: stagnation detection (now via PerceptionBus) ──

_NO_PROGRESS_INDICATORS = [
    "没有进展", "未取得进展", "停滞", "陷入", "原地踏步",
    "no progress", "stuck", "stagnant", "not making progress",
    "going in circles", "没有推进", "无法推进", "效果不佳",
    "repeated", "重复", "ineffective", "无效",
]


def _detect_no_progress(text: str) -> bool:
    """Helper mirroring the original ExecutionService._detect_no_progress."""
    text_lower = text.lower()
    return any(ind in text_lower for ind in _NO_PROGRESS_INDICATORS)


def test_no_progress_chinese(isolated_db):
    assert _detect_no_progress("目前没有进展，需要换一种方式") is True
    # Also test PerceptionBus.record_stagnation works
    bus = PerceptionBus()
    bus.record_stagnation("目前没有进展")
    assert bus.get_stats().stagnation_count == 1


def test_no_progress_english(isolated_db):
    assert _detect_no_progress("We seem to be stuck on this problem") is True


def test_no_progress_negative(isolated_db):
    assert _detect_no_progress("Good progress on the analysis so far") is False


# ── Phase 3: PerceptionBus approval recording ──


def test_record_approve(isolated_db):
    bus = PerceptionBus()
    bus.record_approval("file_write", True, 2.0)

    stats = bus.get_stats()
    assert stats.approval_counts["file_write"] == 1
    assert stats.reject_counts["file_write"] == 0
    assert stats.consecutive_rejects["file_write"] == 0


def test_record_reject(isolated_db):
    bus = PerceptionBus()
    bus.record_approval("file_write", False, 1.0)
    bus.record_approval("file_write", False, 1.5)

    stats = bus.get_stats()
    assert stats.reject_counts["file_write"] == 2
    assert stats.consecutive_rejects["file_write"] == 2


def test_record_reject_reset_on_approve(isolated_db):
    bus = PerceptionBus()
    bus.record_approval("file_write", False, 1.0)
    bus.record_approval("file_write", False, 1.0)
    assert bus.get_stats().consecutive_rejects["file_write"] == 2

    bus.record_approval("file_write", True, 1.0)
    assert bus.get_stats().consecutive_rejects["file_write"] == 0


def test_summary_insufficient_data(isolated_db):
    bus = PerceptionBus()
    bus.record_approval("file_write", True, 1.0)  # only 1 data point
    summary = bus.build_approval_summary()
    # With only 1 data point, should still show something
    assert "file_write" in summary


def test_summary_with_data(isolated_db):
    bus = PerceptionBus()
    for _ in range(5):
        bus.record_approval("file_write", True, 1.0)
    for _ in range(2):
        bus.record_approval("file_write", False, 1.0)

    summary = bus.build_approval_summary()
    assert "file_write" in summary
    assert "5/7" in summary


# ── Phase 3: FirewallEngine auto-escalation ──


def test_escalate_below_threshold(isolated_db):
    cfg = get_config()
    bus = PerceptionBus()
    engine = FirewallEngine(cfg, bus)

    # 2 consecutive rejects (below threshold of 3)
    bus.record_approval("file_delete", False, 1.0)
    bus.record_approval("file_delete", False, 1.0)

    result = engine.should_escalate("file_delete")
    assert result is None


def test_escalate_at_threshold(isolated_db):
    cfg = get_config()
    bus = PerceptionBus()
    engine = FirewallEngine(cfg, bus)

    # 3 consecutive rejects (at threshold)
    bus.record_approval("file_delete", False, 1.0)
    bus.record_approval("file_delete", False, 1.0)
    bus.record_approval("file_delete", False, 1.0)

    result = engine.should_escalate("file_delete")
    assert result == "approve"


# ── Phase 3: _persist_preferences (now on ExecutionService, uses PerceptionBus) ──


def test_persist_high_reject_rate(isolated_db):
    svc = ExecutionService()
    co = svc.co_service.create("Persist test")
    # Record 8 rejects, 2 approves → 80% reject rate
    for _ in range(2):
        svc._perception.record_approval("dangerous_tool", True, 1.0)
    for _ in range(8):
        svc._perception.record_approval("dangerous_tool", False, 1.0)
    svc._persist_preferences(co.id)

    memories = svc.memory_service.retrieve_as_text("preference dangerous_tool", limit=5)
    assert len(memories) >= 1
    assert "reject" in memories[0].lower()
    assert "dangerous_tool" in memories[0]


def test_persist_high_approve_rate(isolated_db):
    svc = ExecutionService()
    co = svc.co_service.create("Persist test")
    # 10 approves, 0 rejects → 0% reject rate, n=10 >= 5
    for _ in range(10):
        svc._perception.record_approval("safe_tool", True, 1.0)
    svc._persist_preferences(co.id)

    memories = svc.memory_service.retrieve_as_text("preference safe_tool", limit=5)
    assert len(memories) >= 1
    assert "approve" in memories[0].lower()


def test_persist_insufficient_data(isolated_db):
    svc = ExecutionService()
    co = svc.co_service.create("Persist test")
    svc._perception.record_approval("rare_tool", True, 1.0)
    svc._perception.record_approval("rare_tool", False, 1.0)
    svc._persist_preferences(co.id)

    memories = svc.memory_service.list_all()
    assert len(memories) == 0


def test_persist_no_duplicate(isolated_db):
    svc = ExecutionService()
    co = svc.co_service.create("Persist test")
    for _ in range(9):
        svc._perception.record_approval("dangerous_tool", False, 1.0)
    svc._perception.record_approval("dangerous_tool", True, 1.0)

    svc._persist_preferences(co.id)
    svc._persist_preferences(co.id)  # second call should be deduped

    memories = svc.memory_service.retrieve_as_text("preference dangerous_tool", limit=10)
    assert len(memories) == 1
