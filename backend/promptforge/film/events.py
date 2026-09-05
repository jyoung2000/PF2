"""Decision log / audit trail (spec X, F): every meaningful choice — by the
user, the Director or the system — lands here with a concise reason and the
data needed to explain it (costs, alternatives). Replay Run reads it back
in order; nothing is ever fabricated after the fact."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import FilmEvent


def log(s: Session, project_id: int | None, title: str, kind: str = "decision",
        reason: str | None = None, data: dict | None = None, stage: str | None = None,
        actor: str = "user", entity: tuple[str, int] | None = None) -> FilmEvent:
    e = FilmEvent(project_id=project_id, kind=kind, stage=stage, actor=actor,
                  title=str(title)[:300], reason=reason, data=data or {},
                  entity_type=entity[0] if entity else None,
                  entity_id=entity[1] if entity else None)
    s.add(e)
    s.flush()
    return e


def event_dict(e: FilmEvent) -> dict:
    return {"id": e.id, "project_id": e.project_id, "at": e.at.isoformat() if e.at else None,
            "kind": e.kind, "stage": e.stage, "actor": e.actor,
            "entity_type": e.entity_type, "entity_id": e.entity_id,
            "title": e.title, "reason": e.reason, "data": e.data or {}}


def list_events(s: Session, project_id: int | None, kind: str | None = None,
                limit: int = 200, ascending: bool = False) -> list[dict]:
    stmt = select(FilmEvent)
    if project_id is not None:
        stmt = stmt.where(FilmEvent.project_id == project_id)
    if kind:
        stmt = stmt.where(FilmEvent.kind == kind)
    stmt = stmt.order_by(FilmEvent.id.asc() if ascending else FilmEvent.id.desc())
    stmt = stmt.limit(max(1, min(limit, 1000)))
    return [event_dict(e) for e in s.execute(stmt).scalars()]
