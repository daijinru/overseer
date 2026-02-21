"""Memory service — cross-event persistent memory storage and retrieval."""

from __future__ import annotations

import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from retro_cogos.database import get_session
from retro_cogos.models.memory import Memory

logger = logging.getLogger(__name__)


class MemoryService:
    def __init__(self, session: Session | None = None):
        self._session = session

    @property
    def session(self) -> Session:
        if self._session is None:
            self._session = get_session()
        return self._session

    def save(
        self,
        category: str,
        content: str,
        tags: list[str] | None = None,
        source_co_id: str | None = None,
    ) -> Memory:
        """Save a memory entry."""
        mem = Memory(
            category=category,
            content=content,
            relevance_tags=tags or [],
            source_co_id=source_co_id,
        )
        self.session.add(mem)
        self.session.commit()
        self.session.refresh(mem)
        logger.info("Saved memory [%s]: %s", category, content[:50])
        return mem

    def retrieve(self, query: str, limit: int = 5) -> List[Memory]:
        """Retrieve relevant memories by keyword matching on content and tags.

        This is a simple tag/keyword matching implementation.
        Can be upgraded to semantic similarity later (Phase 9).
        """
        query_lower = query.lower()
        query_words = set(query_lower.split())

        all_memories = self.session.query(Memory).order_by(Memory.created_at.desc()).limit(100).all()

        scored: list[tuple[float, Memory]] = []
        for mem in all_memories:
            score = 0.0
            content_lower = mem.content.lower()

            # Full query match in content
            if query_lower in content_lower:
                score += 3.0

            # Individual word matches
            for word in query_words:
                if len(word) > 2 and word in content_lower:
                    score += 1.0

            # Tag matches
            tags = mem.relevance_tags or []
            for tag in tags:
                if isinstance(tag, str) and tag.lower() in query_lower:
                    score += 2.0

            if score > 0:
                scored.append((score, mem))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [mem for _, mem in scored[:limit]]

    def retrieve_as_text(self, query: str, limit: int = 5) -> List[str]:
        """Retrieve memories and return as text strings for prompt injection."""
        memories = self.retrieve(query, limit)
        return [f"[{m.category}] {m.content}" for m in memories]

    def extract_and_save(
        self,
        co_id: str,
        llm_response: str,
        step_title: str = "",
    ) -> Optional[Memory]:
        """Extract memorable information from an LLM response.

        Simple heuristic: save responses that mention preferences, patterns, or lessons.
        A more sophisticated approach would use LLM to decide what to remember.
        """
        indicators = [
            "user prefers", "always", "never", "important to note",
            "lesson learned", "pattern", "remember that",
            "用户偏好", "总是", "不要", "重要", "经验", "规律",
        ]
        response_lower = llm_response.lower()
        for indicator in indicators:
            if indicator in response_lower:
                return self.save(
                    category="lesson",
                    content=f"From '{step_title}': {llm_response[:200]}",
                    tags=[step_title] if step_title else [],
                    source_co_id=co_id,
                )
        return None

    def update(
        self,
        memory_id: str,
        category: str | None = None,
        content: str | None = None,
        tags: list[str] | None = None,
    ) -> Memory | None:
        """Update an existing memory. Returns the updated Memory or None."""
        mem = self.session.get(Memory, memory_id)
        if mem is None:
            return None
        if category is not None:
            mem.category = category
        if content is not None:
            mem.content = content
        if tags is not None:
            mem.relevance_tags = tags
        self.session.commit()
        self.session.refresh(mem)
        logger.info("Updated memory %s", memory_id)
        return mem

    def delete(self, memory_id: str) -> bool:
        """Delete a single memory by ID. Returns True if deleted."""
        mem = self.session.get(Memory, memory_id)
        if mem is None:
            return False
        self.session.delete(mem)
        self.session.commit()
        logger.info("Deleted memory %s", memory_id)
        return True

    def list_all(self) -> List[Memory]:
        return self.session.query(Memory).order_by(Memory.created_at.desc()).all()
