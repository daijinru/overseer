"""CognitiveObject ORM model."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy import JSON, DateTime, Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ceo.core.enums import COStatus
from ceo.database import Base


class CognitiveObject(Base):
    __tablename__ = "cognitive_objects"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(
        Enum(COStatus), default=COStatus.CREATED
    )
    context: Mapped[Dict[str, Any]] = mapped_column(
        JSON, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    executions: Mapped[List["Execution"]] = relationship(
        "Execution", back_populates="cognitive_object", order_by="Execution.sequence_number",
        cascade="all, delete-orphan",
    )
    artifacts: Mapped[List["Artifact"]] = relationship(
        "Artifact", back_populates="cognitive_object",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<CO {self.id[:8]} '{self.title}' [{self.status}]>"
