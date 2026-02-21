"""CognitiveObject CRUD service."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from retro_cogos.core.enums import COStatus
from retro_cogos.database import get_session
from retro_cogos.models.cognitive_object import CognitiveObject
from retro_cogos.models.memory import Memory


class CognitiveObjectService:
    def __init__(self, session: Session | None = None):
        self._session = session

    @property
    def session(self) -> Session:
        if self._session is None:
            self._session = get_session()
        return self._session

    def create(self, title: str, description: str = "") -> CognitiveObject:
        co = CognitiveObject(
            title=title,
            description=description,
            context={"goal": title, "accumulated_findings": [], "step_count": 0},
        )
        self.session.add(co)
        self.session.commit()
        self.session.refresh(co)
        return co

    def get(self, co_id: str) -> Optional[CognitiveObject]:
        return self.session.get(CognitiveObject, co_id)

    def list_all(self) -> List[CognitiveObject]:
        return (
            self.session.query(CognitiveObject)
            .order_by(CognitiveObject.created_at.desc())
            .all()
        )

    def update_status(self, co_id: str, new_status: COStatus) -> Optional[CognitiveObject]:
        co = self.get(co_id)
        if co is None:
            return None
        co.status = new_status
        self.session.commit()
        self.session.refresh(co)
        return co

    def update_context(self, co_id: str, context: dict) -> Optional[CognitiveObject]:
        co = self.get(co_id)
        if co is None:
            return None
        co.context = context
        self.session.commit()
        self.session.refresh(co)
        return co

    def delete(self, co_id: str) -> bool:
        co = self.get(co_id)
        if co is None:
            return False
        # Clear memory references to avoid FK constraint violations on old schemas
        self.session.query(Memory).filter(Memory.source_co_id == co_id).update(
            {"source_co_id": None}
        )
        self.session.delete(co)
        self.session.commit()
        return True

    def delete_all(self) -> int:
        cos = self.list_all()
        count = len(cos)
        co_ids = [co.id for co in cos]
        if co_ids:
            self.session.query(Memory).filter(Memory.source_co_id.in_(co_ids)).update(
                {"source_co_id": None}
            )
        for co in cos:
            self.session.delete(co)
        self.session.commit()
        return count
