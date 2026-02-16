"""Execution ORM model."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ceo.core.enums import ExecutionStatus
from ceo.database import Base


class Execution(Base):
    __tablename__ = "executions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    cognitive_object_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cognitive_objects.id"), index=True
    )
    sequence_number: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(
        Enum(ExecutionStatus), default=ExecutionStatus.PENDING
    )
    prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    llm_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    llm_decision: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    tool_calls: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSON, nullable=True)
    tool_results: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSON, nullable=True)
    human_decision: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    human_input: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    cognitive_object: Mapped["CognitiveObject"] = relationship(
        "CognitiveObject", back_populates="executions"
    )

    def __repr__(self) -> str:
        return f"<Exec #{self.sequence_number} '{self.title}' [{self.status}]>"
