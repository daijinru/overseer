"""Tests for ORM models — Phase 2 verification."""

from overseer.core.enums import COStatus, ExecutionStatus
from overseer.core.protocols import LLMDecision
from overseer.database import get_session
from overseer.models.cognitive_object import CognitiveObject
from overseer.models.execution import Execution
from overseer.models.memory import Memory
from overseer.models.artifact import Artifact


def test_create_cognitive_object(isolated_db):
    session = get_session()
    co = CognitiveObject(title="Test CO", description="A test event")
    session.add(co)
    session.commit()
    session.refresh(co)

    assert co.id is not None
    assert co.title == "Test CO"
    assert co.status == COStatus.CREATED
    assert co.context == {}
    session.close()


def test_create_execution(isolated_db):
    session = get_session()
    co = CognitiveObject(title="Test CO")
    session.add(co)
    session.commit()
    session.refresh(co)

    ex = Execution(
        cognitive_object_id=co.id,
        sequence_number=1,
        title="Step 1",
        status=ExecutionStatus.PENDING,
    )
    session.add(ex)
    session.commit()
    session.refresh(ex)

    assert ex.id is not None
    assert ex.cognitive_object_id == co.id
    assert ex.status == ExecutionStatus.PENDING
    session.close()


def test_co_execution_relationship(isolated_db):
    session = get_session()
    co = CognitiveObject(title="Test CO")
    session.add(co)
    session.commit()
    session.refresh(co)

    for i in range(3):
        ex = Execution(
            cognitive_object_id=co.id,
            sequence_number=i + 1,
            title=f"Step {i + 1}",
        )
        session.add(ex)
    session.commit()
    session.refresh(co)

    assert len(co.executions) == 3
    assert co.executions[0].sequence_number == 1
    assert co.executions[2].sequence_number == 3
    session.close()


def test_create_memory(isolated_db):
    session = get_session()
    mem = Memory(
        category="preference",
        content="User prefers detailed reports",
        relevance_tags=["report", "style"],
    )
    session.add(mem)
    session.commit()
    session.refresh(mem)

    assert mem.id is not None
    assert mem.category == "preference"
    assert "report" in mem.relevance_tags
    session.close()


def test_create_artifact(isolated_db):
    session = get_session()
    co = CognitiveObject(title="Test CO")
    session.add(co)
    session.commit()
    session.refresh(co)

    art = Artifact(
        cognitive_object_id=co.id,
        name="report.md",
        file_path="/tmp/report.md",
        artifact_type="report",
    )
    session.add(art)
    session.commit()
    session.refresh(art)

    assert art.id is not None
    assert art.artifact_type == "report"
    assert co.artifacts[0].name == "report.md"
    session.close()


def test_llm_decision_parse():
    """Verify LLMDecision Pydantic model parses the documented JSON example."""
    data = {
        "next_action": {
            "title": "分析营收构成明细",
            "description": "上一步发现营收下降 12%，需要按业务线拆解原因",
        },
        "tool_calls": [
            {"tool": "file_read", "args": {"path": "data/revenue_breakdown.csv"}}
        ],
        "human_required": False,
        "human_reason": None,
        "options": [],
        "task_complete": False,
        "confidence": 0.85,
        "reflection": "前两步收集了宏观数据，现在需要深入细节",
    }
    decision = LLMDecision(**data)
    assert decision.next_action.title == "分析营收构成明细"
    assert len(decision.tool_calls) == 1
    assert decision.tool_calls[0].tool == "file_read"
    assert decision.confidence == 0.85
    assert decision.task_complete is False


def test_llm_decision_human_required():
    data = {
        "human_required": True,
        "human_reason": "发现两种可能的原因方向",
        "options": ["调查市场份额", "调查定价策略", "两个都调查"],
    }
    decision = LLMDecision(**data)
    assert decision.human_required is True
    assert len(decision.options) == 3
