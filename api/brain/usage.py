"""Usage tracking — which knowledge actually gets reused.

Every time the Brain answers a question or an agent searches, the knowledge
items that were cited get a usage event. This lets you see which atoms are
actually valuable vs. which are just sitting there.

Usage data is append-only and lightweight — just a row per citation event.
"""

from __future__ import annotations

from datetime import UTC, datetime
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import new_id
from .harness import Base
from sqlalchemy import String, Text, DateTime, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column


class UsageEvent(Base):
    """One citation of a knowledge atom."""
    __tablename__ = "usage_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    knowledge_id: Mapped[str] = mapped_column(ForeignKey("knowledge.id"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    context: Mapped[str] = mapped_column(String(40), default="search")  # search, answer, draft, export
    query: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


def track_usage(
    db: Session,
    workspace_id: str,
    knowledge_id: str,
    context: str = "search",
    query: str = "",
) -> UsageEvent:
    """Record that a knowledge atom was used."""
    event = UsageEvent(
        id=new_id("use"),
        knowledge_id=knowledge_id,
        workspace_id=workspace_id,
        context=context,
        query=query[:500],
    )
    db.add(event)
    db.flush()
    return event


def track_batch(
    db: Session,
    workspace_id: str,
    knowledge_ids: list[str],
    context: str = "search",
    query: str = "",
) -> int:
    """Record usage for multiple knowledge atoms at once."""
    for kid in knowledge_ids:
        track_usage(db, workspace_id, kid, context, query)
    db.commit()
    return len(knowledge_ids)


def top_used(
    db: Session,
    workspace_id: str,
    limit: int = 10,
    since_days: int = 30,
) -> list[dict]:
    """Most-used knowledge atoms in the workspace."""
    from .models import Knowledge
    since = datetime.now(UTC) - __import__("datetime").timedelta(days=since_days)
    rows = list(db.execute(
        select(
            UsageEvent.knowledge_id,
            func.count(UsageEvent.id).label("usage_count"),
            Knowledge.statement,
            Knowledge.type,
        )
        .join(Knowledge, Knowledge.id == UsageEvent.knowledge_id)
        .where(
            UsageEvent.workspace_id == workspace_id,
            UsageEvent.created_at >= since,
        )
        .group_by(UsageEvent.knowledge_id)
        .order_by(func.count(UsageEvent.id).desc())
        .limit(limit)
    ).all())
    return [
        {"knowledge_id": r[0], "count": r[1], "statement": r[2][:120], "type": r[3]}
        for r in rows
    ]


def unused_knowledge(
    db: Session,
    workspace_id: str,
    limit: int = 10,
) -> list[dict]:
    """Canonical knowledge that has never been cited."""
    from .models import Knowledge
    used_ids = select(UsageEvent.knowledge_id).where(
        UsageEvent.workspace_id == workspace_id
    ).scalar_subquery()
    items = list(db.scalars(
        select(Knowledge).where(
            Knowledge.workspace_id == workspace_id,
            Knowledge.status == "canonical",
            Knowledge.id.notin_(used_ids),
        ).order_by(Knowledge.approved_at).limit(limit)
    ).all())
    return [
        {"id": k.id, "statement": k.statement[:120], "type": k.type, "approved_at": k.approved_at.isoformat()}
        for k in items
    ]


def usage_summary(db: Session, workspace_id: str) -> dict:
    """Overview of knowledge usage patterns."""
    from .models import Knowledge
    total_knowledge = db.scalar(
        select(func.count(Knowledge.id)).where(
            Knowledge.workspace_id == workspace_id,
            Knowledge.status == "canonical",
        )
    ) or 0
    total_usage = db.scalar(
        select(func.count(UsageEvent.id)).where(
            UsageEvent.workspace_id == workspace_id,
        )
    ) or 0
    unique_used = db.scalar(
        select(func.count(func.distinct(UsageEvent.knowledge_id))).where(
            UsageEvent.workspace_id == workspace_id,
        )
    ) or 0
    return {
        "total_knowledge": total_knowledge,
        "total_usage_events": total_usage,
        "unique_atoms_used": unique_used,
        "reuse_rate": round(unique_used / max(total_knowledge, 1), 2),
        "top_used": top_used(db, workspace_id, limit=5),
        "unused_count": max(total_knowledge - unique_used, 0),
    }