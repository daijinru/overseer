"""Artifact ORM model — files and data produced during execution."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ceo.database import Base


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    cognitive_object_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cognitive_objects.id"), index=True
    )
    execution_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("executions.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(Text)
    artifact_type: Mapped[str] = mapped_column(
        String(50)  # report / data / chart / document
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    cognitive_object: Mapped["CognitiveObject"] = relationship(
        "CognitiveObject", back_populates="artifacts"
    )

    def __repr__(self) -> str:
        return f"<Artifact '{self.name}' [{self.artifact_type}]>"
