"""The "couldn't answer" log, and the Today summary that opens the console.

Every question the Brain declines (through the console or an agent's
``ask_brain``) is recorded, folded together with earlier askings of the same
question, so the gaps people actually hit are visible. A row closes on its
own when the same question is later answered from approved knowledge, or a
person dismisses it. Only owners and admins read the log: questions can name
private things.

``build_today`` gathers what needs a person right now in one read: the review
queue, gardening, the log, failing folder syncs and agents' live notes.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .access import ReadScope
from .extraction import statement_terms
from .models import (
    AgentNote,
    ConnectorWatch,
    Knowledge,
    Proposal,
    Source,
    UnansweredQuestion,
    new_id,
)
from .schemas import ChatResponse
from .services import aware_utc

log = logging.getLogger(__name__)


def question_key(question: str) -> str:
    """Same significant words, same question: "Who owns billing?" == "who owns the billing"."""
    terms = sorted(statement_terms(question))
    return " ".join(terms)[:240] or question.strip().lower()[:240]


def record_answer(
    db: Session,
    workspace_id: str,
    question: str,
    result: ChatResponse,
    *,
    via: str = "console",
    now: datetime | None = None,
) -> UnansweredQuestion | None:
    """Log a declined question, or close its row once it is answered. Never raises."""
    now = now or datetime.now(UTC)
    try:
        key = question_key(question)
        row = db.scalar(
            select(UnansweredQuestion).where(
                UnansweredQuestion.workspace_id == workspace_id, UnansweredQuestion.key == key
            )
        )
        if result.grounded:
            if row is not None and row.status == "open":
                row.status = "answered"
                row.resolved_at = now
                db.commit()
            return row
        near = [match.knowledge_id for match in result.near_matches][:5]
        if row is None:
            row = UnansweredQuestion(
                id=new_id("unq"),
                workspace_id=workspace_id,
                key=key,
                question=question.strip(),
                via=via,
                near_ids=json.dumps(near),
                first_asked_at=now,
                last_asked_at=now,
            )
            db.add(row)
        else:
            row.question = question.strip()
            row.times_asked += 1
            row.via = via
            row.near_ids = json.dumps(near)
            row.last_asked_at = now
            if row.status != "open":
                # Asked again and still not answered: it is a gap again.
                row.status = "open"
                row.resolved_at = None
        db.commit()
        return row
    except Exception as exc:  # logging must never break an answer
        db.rollback()
        log.warning("Could not record an unanswered question: %s", exc)
        return None


def list_unanswered(
    db: Session, workspace_id: str, *, status: str = "open", limit: int = 50
) -> list[UnansweredQuestion]:
    stmt = select(UnansweredQuestion).where(UnansweredQuestion.workspace_id == workspace_id)
    if status != "all":
        stmt = stmt.where(UnansweredQuestion.status == status)
    return list(
        db.scalars(
            stmt.order_by(
                UnansweredQuestion.times_asked.desc(), UnansweredQuestion.last_asked_at.desc()
            ).limit(limit)
        )
    )


@dataclass
class TodayItem:
    key: str
    count: int
    label: str
    view: str
    detail: str = ""


@dataclass
class Today:
    generated_at: str
    items: list[TodayItem] = field(default_factory=list)
    top_unanswered: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _plural(count: int, one: str, many: str) -> str:
    return one if count == 1 else many


def build_today(
    db: Session, scope: ReadScope, *, can_administer: bool, now: datetime | None = None
) -> Today:
    """What needs a person today, each with the console view that handles it."""
    from .gardening import build_gardening

    now = now or datetime.now(UTC)
    today = Today(generated_at=now.isoformat())

    pending = list(
        db.scalars(
            scope.apply(select(Proposal.created_at).where(Proposal.status == "proposed"), Proposal)
        )
    )
    if pending:
        oldest = min(aware_utc(value) for value in pending)
        days = (now - oldest).days
        today.items.append(
            TodayItem(
                "reviews",
                len(pending),
                f"{len(pending)} {_plural(len(pending), 'suggestion', 'suggestions')} to review",
                "inbox",
                f"Oldest waiting {days} {_plural(days, 'day', 'days')}" if days else "",
            )
        )

    report = build_gardening(db, scope, now=now)
    if report.total():
        counts = {key: value for key, value in report.counts().items() if value}
        labels = dict(report.SECTIONS)
        today.items.append(
            TodayItem(
                "gardening",
                report.total(),
                f"{report.total()} approved {_plural(report.total(), 'item needs', 'items need')} a look",
                "overview",
                ", ".join(f"{labels[key].lower()} {value}" for key, value in counts.items()),
            )
        )

    if can_administer:
        open_rows = list_unanswered(db, scope.workspace_id, limit=5)
        open_count = db.scalar(
            select(func.count(UnansweredQuestion.id)).where(
                UnansweredQuestion.workspace_id == scope.workspace_id,
                UnansweredQuestion.status == "open",
            )
        )
        if open_count:
            today.items.append(
                TodayItem(
                    "unanswered",
                    open_count,
                    f"{open_count} {_plural(open_count, 'question', 'questions')} the Brain couldn't answer",
                    "ask",
                )
            )
            today.top_unanswered = [
                {"id": row.id, "question": row.question, "times_asked": row.times_asked}
                for row in open_rows
            ]

    failing = [
        watch.label or watch.folder_id
        for watch in db.scalars(
            select(ConnectorWatch).where(ConnectorWatch.workspace_id == scope.workspace_id)
        )
        if watch.last_result.startswith("Listing failed")
    ]
    if failing:
        today.items.append(
            TodayItem(
                "sync",
                len(failing),
                f"{len(failing)} watched {_plural(len(failing), 'folder', 'folders')} failed to sync",
                "connectors",
                ", ".join(failing[:3]),
            )
        )

    since = now - timedelta(days=1)
    captured = db.scalar(
        scope.apply(select(func.count(Source.id)).where(Source.created_at >= since), Source)
    )
    approved = db.scalar(
        scope.apply(
            select(func.count(Knowledge.id)).where(
                Knowledge.status == "canonical", Knowledge.approved_at >= now - timedelta(days=7)
            ),
            Knowledge,
        )
    )
    notes = db.scalar(
        select(func.count(AgentNote.id)).where(
            AgentNote.workspace_id == scope.workspace_id,
            AgentNote.sensitivity.in_(scope.permitted),
            AgentNote.expires_at > now,
        )
    )
    if captured:
        today.items.append(
            TodayItem(
                "captured",
                captured,
                f"{captured} new {_plural(captured, 'source', 'sources')} since yesterday",
                "sources",
            )
        )
    if approved:
        today.items.append(
            TodayItem(
                "approved",
                approved,
                f"{approved} {_plural(approved, 'item', 'items')} approved this week",
                "brain",
            )
        )
    if notes:
        today.items.append(
            TodayItem(
                "notes",
                notes,
                f"{notes} agent working {_plural(notes, 'note', 'notes')}",
                "working-memory",
            )
        )
    return today
