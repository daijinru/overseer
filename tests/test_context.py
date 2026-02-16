"""Tests for context service — Phase 4 verification."""

import json

from ceo.services.cognitive_object_service import CognitiveObjectService
from ceo.services.context_service import ContextService


def test_build_prompt(isolated_db):
    co_svc = CognitiveObjectService()
    ctx_svc = ContextService()

    co = co_svc.create("Investigate Q4 report", "Find revenue anomalies")
    prompt = ctx_svc.build_prompt(co)

    assert "Investigate Q4 report" in prompt
    assert "Find revenue anomalies" in prompt
    assert "Instructions" in prompt


def test_build_prompt_with_memories(isolated_db):
    co_svc = CognitiveObjectService()
    ctx_svc = ContextService()

    co = co_svc.create("Q4 analysis")
    memories = ["User always wants cash flow analysis", "Previous report format: PDF"]
    prompt = ctx_svc.build_prompt(co, memories)

    assert "cash flow" in prompt
    assert "PDF" in prompt
    assert "Relevant Memories" in prompt


def test_merge_step_result(isolated_db):
    co_svc = CognitiveObjectService()
    ctx_svc = ContextService()

    co = co_svc.create("Test")
    ctx_svc.merge_step_result(co, 1, "revenue_trend", "Q4 revenue down 12%")

    co = co_svc.get(co.id)  # refresh
    findings = co.context.get("accumulated_findings", [])
    assert len(findings) == 1
    assert findings[0]["key"] == "revenue_trend"
    assert findings[0]["step"] == 1


def test_merge_tool_result(isolated_db):
    co_svc = CognitiveObjectService()
    ctx_svc = ContextService()

    co = co_svc.create("Test")
    ctx_svc.merge_tool_result(co, 1, "file_read", '{"status": "ok", "content": "data..."}')

    co = co_svc.get(co.id)
    findings = co.context.get("accumulated_findings", [])
    assert findings[0]["key"] == "tool:file_read"


def test_merge_reflection(isolated_db):
    co_svc = CognitiveObjectService()
    ctx_svc = ContextService()

    co = co_svc.create("Test")
    ctx_svc.merge_reflection(co, "Good progress so far")

    co = co_svc.get(co.id)
    assert co.context.get("last_reflection") == "Good progress so far"


def test_compress_if_needed(isolated_db):
    co_svc = CognitiveObjectService()
    ctx_svc = ContextService()

    co = co_svc.create("Test")

    # Add many findings to exceed the threshold
    for i in range(20):
        ctx_svc.merge_step_result(co, i + 1, f"finding_{i}", "x" * 800)

    co = co_svc.get(co.id)
    original_count = len(co.context.get("accumulated_findings", []))
    assert original_count == 20

    compressed = ctx_svc.compress_if_needed(co, max_chars=5000)
    assert compressed is True

    co = co_svc.get(co.id)
    new_count = len(co.context.get("accumulated_findings", []))
    assert new_count < original_count
    # First entry should be a compressed summary
    assert co.context["accumulated_findings"][0]["key"] == "compressed_summary"


def test_add_artifact(isolated_db):
    co_svc = CognitiveObjectService()
    ctx_svc = ContextService()

    co = co_svc.create("Test")
    ctx_svc.add_artifact(co, "/tmp/report.md")

    co = co_svc.get(co.id)
    assert "/tmp/report.md" in co.context.get("artifacts_produced", [])
