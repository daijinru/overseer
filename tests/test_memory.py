"""Tests for memory service — Phase 4 verification."""

from retro_cogos.services.memory_service import MemoryService


def test_save_memory(isolated_db):
    svc = MemoryService()
    mem = svc.save("preference", "User prefers PDF reports", tags=["report", "format"])
    assert mem.id is not None
    assert mem.category == "preference"
    assert "report" in mem.relevance_tags


def test_retrieve_by_keyword(isolated_db):
    svc = MemoryService()
    svc.save("preference", "User prefers PDF reports", tags=["report"])
    svc.save("lesson", "Always check cash flow in financial analysis", tags=["finance"])
    svc.save("domain_knowledge", "Python is a programming language", tags=["tech"])

    results = svc.retrieve("financial report")
    # Should match the finance lesson and possibly the report preference
    assert len(results) >= 1
    contents = [r.content for r in results]
    assert any("financial" in c.lower() for c in contents)


def test_retrieve_by_tags(isolated_db):
    svc = MemoryService()
    svc.save("preference", "Some preference", tags=["finance", "quarterly"])
    svc.save("lesson", "Another lesson", tags=["tech"])

    results = svc.retrieve("finance quarterly analysis")
    assert len(results) >= 1


def test_retrieve_as_text(isolated_db):
    svc = MemoryService()
    svc.save("preference", "User prefers detailed analysis", tags=["analysis"])

    texts = svc.retrieve_as_text("detailed analysis")
    assert len(texts) >= 1
    assert texts[0].startswith("[preference]")


def test_extract_and_save(isolated_db):
    svc = MemoryService()

    # Response with a memory-worthy indicator — use None for source_co_id
    response = "Important to note: the user always wants quarterly comparisons included."
    mem = svc.extract_and_save(None, response, "Analysis step")
    assert mem is not None
    assert mem.category == "lesson"

    # Response without indicators
    response = "The data shows normal trends."
    mem = svc.extract_and_save(None, response, "Check step")
    assert mem is None


def test_list_all(isolated_db):
    svc = MemoryService()
    svc.save("a", "Memory 1")
    svc.save("b", "Memory 2")
    all_mems = svc.list_all()
    assert len(all_mems) == 2
