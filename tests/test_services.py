"""Tests for service layer — Phase 3 verification."""

from ceo.core.enums import COStatus
from ceo.services.cognitive_object_service import CognitiveObjectService
from ceo.services.llm_service import LLMService


def test_co_service_create(isolated_db):
    svc = CognitiveObjectService()
    co = svc.create("Test Event", "A test description")
    assert co.id is not None
    assert co.title == "Test Event"
    assert co.status == COStatus.CREATED
    assert co.context.get("goal") == "Test Event"


def test_co_service_list_all(isolated_db):
    svc = CognitiveObjectService()
    svc.create("Event 1")
    svc.create("Event 2")
    svc.create("Event 3")
    all_cos = svc.list_all()
    assert len(all_cos) == 3


def test_co_service_update_status(isolated_db):
    svc = CognitiveObjectService()
    co = svc.create("Test Event")
    updated = svc.update_status(co.id, COStatus.RUNNING)
    assert updated.status == COStatus.RUNNING
    updated = svc.update_status(co.id, COStatus.PAUSED)
    assert updated.status == COStatus.PAUSED


def test_co_service_update_context(isolated_db):
    svc = CognitiveObjectService()
    co = svc.create("Test Event")
    new_ctx = {"goal": "Test Event", "step_count": 2, "accumulated_findings": []}
    updated = svc.update_context(co.id, new_ctx)
    assert updated.context["step_count"] == 2


def test_co_service_delete(isolated_db):
    svc = CognitiveObjectService()
    co = svc.create("To Delete")
    assert svc.delete(co.id) is True
    assert svc.get(co.id) is None


def test_llm_decision_parse_from_response():
    """Test LLMService.parse_decision with a realistic response."""
    svc = LLMService()

    response = """I analyzed the quarterly data and found significant trends.

```decision
{
  "next_action": {"title": "Deep dive into B2B segment", "description": "B2B revenue dropped 18%"},
  "tool_calls": [],
  "human_required": false,
  "task_complete": false,
  "confidence": 0.8,
  "reflection": "Making good progress on data analysis"
}
```"""

    decision = svc.parse_decision(response)
    assert decision.next_action.title == "Deep dive into B2B segment"
    assert decision.task_complete is False
    assert decision.confidence == 0.8


def test_llm_decision_parse_fallback():
    """Test parse_decision fallback when no proper block is found."""
    svc = LLMService()
    response = "I'm not sure what to do next. Here's my analysis..."
    decision = svc.parse_decision(response)
    # Should fall back to requesting human input
    assert decision.human_required is True
