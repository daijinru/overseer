"""Tests for artifact service — Phase 5 verification."""

from ceo.services.artifact_service import ArtifactService
from ceo.services.cognitive_object_service import CognitiveObjectService
from ceo.database import get_session
from ceo.models.execution import Execution


def _create_co_and_exec(co_title="Test"):
    """Helper: create a CO and an Execution, return (co, exec)."""
    co_svc = CognitiveObjectService()
    co = co_svc.create(co_title)
    session = get_session()
    ex = Execution(cognitive_object_id=co.id, sequence_number=1, title="Step 1")
    session.add(ex)
    session.commit()
    session.refresh(ex)
    return co, ex


def test_record_artifact(isolated_db, tmp_path):
    co, ex = _create_co_and_exec()
    art_svc = ArtifactService()

    art = art_svc.record(
        co_id=co.id,
        execution_id=ex.id,
        name="report.md",
        file_path=str(tmp_path / "report.md"),
        artifact_type="report",
    )
    assert art.id is not None
    assert art.name == "report.md"
    assert art.artifact_type == "report"


def test_list_for_co(isolated_db, tmp_path):
    co, ex = _create_co_and_exec()
    art_svc = ArtifactService()

    art_svc.record(co.id, ex.id, "file1.txt", str(tmp_path / "f1"), "data")
    art_svc.record(co.id, ex.id, "file2.md", str(tmp_path / "f2"), "report")

    arts = art_svc.list_for_co(co.id)
    assert len(arts) == 2


def test_get_output_dir(isolated_db, tmp_path):
    art_svc = ArtifactService()
    output_dir = art_svc.get_output_dir()
    assert output_dir.exists()
