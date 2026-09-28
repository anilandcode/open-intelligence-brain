"""Usage tracking — which knowledge actually gets reused.

Every time the Brain answers a question or an agent searches, the knowledge
items that were cited get a usage event. This lets you see which atoms are
actually valuable vs. which are just sitting there.

Usage data is append-only and lightweight — just a row per citation event.

Reads take a ReadScope like every other collection read: counts and listings
that include private material would leak its existence to a member, so every
query here narrows Knowledge by workspace AND sensitivity ceiling.

This module MUST be imported at main.py module level (not lazily inside a
route body) so UsageEvent is registered on Base before lifespan's create_all
runs — otherwise usage_events never exists on a fresh database and every
/api/v1/usage* route 500s.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, ForeignKey, String, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .access import ReadScope
from .harness import Base
from .models import Knowledge, new_id


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
    scope: ReadScope,
    limit: int = 10,
    since_days: int = 30,
) -> list[dict]:
    """Most-used knowledge atoms the caller may read."""
    since = datetime.now(UTC) - timedelta(days=since_days)
    stmt = (
        select(
            UsageEvent.knowledge_id,
            func.count(UsageEvent.id).label("usage_count"),
            Knowledge.statement,
            Knowledge.type,
        )
        .join(Knowledge, Knowledge.id == UsageEvent.knowledge_id)
        .where(
            UsageEvent.workspace_id == scope.workspace_id,
            UsageEvent.created_at >= since,
        )
        .group_by(UsageEvent.knowledge_id)
        .order_by(func.count(UsageEvent.id).desc())
        .limit(limit)
    )
    # Narrow through the Knowledge side of the join: a member must not see
    # usage rows — or statements — for private atoms.
    stmt = scope.apply(stmt, Knowledge)
    rows = list(db.execute(stmt).all())
    return [
        {"knowledge_id": r[0], "count": r[1], "statement": r[2][:120], "type": r[3]}
        for r in rows
    ]


def unused_knowledge(
    db: Session,
    scope: ReadScope,
    limit: int = 10,
) -> list[dict]:
    """Canonical knowledge the caller may read that has never been cited."""
    used_ids = select(UsageEvent.knowledge_id).where(
        UsageEvent.workspace_id == scope.workspace_id
    ).scalar_subquery()
    stmt = scope.apply(
        select(Knowledge).where(
            Knowledge.status == "canonical",
            Knowledge.id.notin_(used_ids),
        ),
        Knowledge,
    )
    items = list(db.scalars(stmt.order_by(Knowledge.approved_at).limit(limit)).all())
    return [
        {"id": k.id, "statement": k.statement[:120], "type": k.type, "approved_at": k.approved_at.isoformat()}
        for k in items
    ]


def usage_summary(db: Session, scope: ReadScope) -> dict:
    """Overview of knowledge usage patterns, narrowed to the caller's ceiling."""
    total_knowledge = db.scalar(
        scope.apply(
            select(func.count(Knowledge.id)).where(Knowledge.status == "canonical"),
            Knowledge,
        )
    ) or 0
    # Count only events whose atom the caller may read, so totals cannot leak
    # the existence of private rows through the numbers alone.
    readable_ids = scope.apply(select(Knowledge.id), Knowledge).scalar_subquery()
    total_usage = db.scalar(
        select(func.count(UsageEvent.id)).where(
            UsageEvent.workspace_id == scope.workspace_id,
            UsageEvent.knowledge_id.in_(readable_ids),
        )
    ) or 0
    unique_used = db.scalar(
        select(func.count(func.distinct(UsageEvent.knowledge_id))).where(
            UsageEvent.workspace_id == scope.workspace_id,
            UsageEvent.knowledge_id.in_(readable_ids),
        )
    ) or 0
    return {
        "total_knowledge": total_knowledge,
        "total_usage_events": total_usage,
        "unique_atoms_used": unique_used,
        "reuse_rate": round(unique_used / max(total_knowledge, 1), 2),
        "top_used": top_used(db, scope, limit=5),
        "unused_count": max(total_knowledge - unique_used, 0),
    }
