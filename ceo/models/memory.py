"""Memory ORM model — cross-event persistent memory."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ceo.database import Base


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    category: Mapped[str] = mapped_column(
        String(50)  # preference / decision_pattern / domain_knowledge / lesson
    )
    content: Mapped[str] = mapped_column(Text)
    source_co_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("cognitive_objects.id", ondelete="SET NULL"), nullable=True
    )
    relevance_tags: Mapped[Dict[str, Any]] = mapped_column(
        JSON, default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return f"<Memory [{self.category}] {self.content[:30]}...>"
