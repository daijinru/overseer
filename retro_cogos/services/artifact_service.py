"""Artifact service — records and manages files produced during execution."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from sqlalchemy.orm import Session

from retro_cogos.config import get_config
from retro_cogos.database import get_session
from retro_cogos.models.artifact import Artifact

logger = logging.getLogger(__name__)


class ArtifactService:
    def __init__(self, session: Session | None = None):
        self._session = session

    @property
    def session(self) -> Session:
        if self._session is None:
            self._session = get_session()
        return self._session

    def record(
        self,
        co_id: str,
        execution_id: str,
        name: str,
        file_path: str,
        artifact_type: str = "document",
    ) -> Artifact:
        """Record an artifact in the database."""
        artifact = Artifact(
            cognitive_object_id=co_id,
            execution_id=execution_id,
            name=name,
            file_path=str(Path(file_path).resolve()),
            artifact_type=artifact_type,
        )
        self.session.add(artifact)
        self.session.commit()
        self.session.refresh(artifact)
        logger.info("Recorded artifact: %s at %s", name, file_path)
        return artifact

    def list_for_co(self, co_id: str) -> List[Artifact]:
        """List all artifacts for a CognitiveObject."""
        return (
            self.session.query(Artifact)
            .filter_by(cognitive_object_id=co_id)
            .order_by(Artifact.created_at)
            .all()
        )

    def get_output_dir(self) -> Path:
        """Get the configured output directory, creating it if needed."""
        cfg = get_config()
        output_dir = Path(cfg.context.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir
