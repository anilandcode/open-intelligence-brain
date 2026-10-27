"""Gardening: the weekly list of approved knowledge that needs a person.

Approved knowledge decays. Prices change, owners move, plans finish, and an
item nobody has used in months may no longer be worth keeping. This report
collects what needs a decision, each with a link that opens the item:

- due for review: its review-by date has passed;
- expired: past its expiry date, so it is no longer cited as an answer;
- source changed: the sentence it rests on changed in a newer version;
- possible conflicts: two items that say opposite things;
- possible duplicates: two items that say nearly the same thing;
- unused: approved long ago and not cited by any answer, search or agent since.

Everything is read through the caller's ReadScope, so a member's report never
names private knowledge. Nothing here changes knowledge; the console's
"Mark reviewed", date and revision controls do that.

Usage from a shell (for a weekly cron on the VM):
    python -m brain.gardening default           # print the report
    python -m brain.gardening default --send    # send it through Hermes
"""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .access import ReadScope
from .claims import term_overlap
from .config import get_settings
from .extraction import statement_terms
from .models import AuditEvent, Knowledge, Workspace
from .services import audit, aware_utc, is_due_for_review, is_expired, knowledge_is_stale
from .usage import UsageEvent

DUPLICATE_OVERLAP = 0.6
MAX_PAIR_ITEMS = 500


@dataclass
class GardenItem:
    knowledge_id: str
    statement: str
    detail: str
    related_id: str | None = None


@dataclass
class GardenReport:
    generated_at: str
    due_for_review: list[GardenItem] = field(default_factory=list)
    expired: list[GardenItem] = field(default_factory=list)
    source_changed: list[GardenItem] = field(default_factory=list)
    conflicts: list[GardenItem] = field(default_factory=list)
    duplicates: list[GardenItem] = field(default_factory=list)
    unused: list[GardenItem] = field(default_factory=list)

    SECTIONS = (
        ("due_for_review", "Due for review"),
        ("expired", "Expired"),
        ("source_changed", "Source changed"),
        ("conflicts", "Possible conflicts"),
        ("duplicates", "Possible duplicates"),
        ("unused", "Not used lately"),
    )

    def counts(self) -> dict[str, int]:
        return {key: len(getattr(self, key)) for key, _ in self.SECTIONS}

    def total(self) -> int:
        return sum(self.counts().values())

    def to_dict(self) -> dict:
        return {**asdict(self), "counts": self.counts(), "total": self.total()}


def _short(text: str, size: int = 140) -> str:
    return text if len(text) <= size else text[: size - 1].rstrip() + "…"


def _date(value: datetime | None) -> str:
    return aware_utc(value).date().isoformat() if value else ""


def build_gardening(
    db: Session, scope: ReadScope, *, now: datetime | None = None, limit: int = 10
) -> GardenReport:
    now = now or datetime.now(UTC)
    settings = get_settings()
    items = list(
        db.scalars(
            scope.apply(
                select(Knowledge).where(Knowledge.status == "canonical"), Knowledge
            ).order_by(Knowledge.approved_at)
        )
    )
    report = GardenReport(generated_at=now.isoformat())

    due = sorted(
        (i for i in items if is_due_for_review(i, now)), key=lambda i: aware_utc(i.review_by)
    )
    report.due_for_review = [
        GardenItem(i.id, _short(i.statement), f"Review was due {_date(i.review_by)}")
        for i in due[:limit]
    ]
    expired = [i for i in items if is_expired(i, now)]
    report.expired = [
        GardenItem(i.id, _short(i.statement), f"Expired {_date(i.expires_at)}")
        for i in expired[:limit]
    ]
    report.source_changed = [
        GardenItem(i.id, _short(i.statement), "The sentence it rests on changed in a newer version")
        for i in items
        if knowledge_is_stale(db, i)
    ][:limit]

    pool = items[-MAX_PAIR_ITEMS:]
    terms = {i.id: statement_terms(i.statement) for i in pool}
    for index, left in enumerate(pool):
        for right in pool[index + 1 :]:
            score = term_overlap(terms[left.id], terms[right.id])
            if score < DUPLICATE_OVERLAP:
                continue
            opposite = ("<negated>" in terms[left.id]) != ("<negated>" in terms[right.id])
            target = report.conflicts if opposite else report.duplicates
            if len(target) < limit:
                target.append(
                    GardenItem(
                        left.id,
                        _short(left.statement),
                        f"{'Says the opposite of' if opposite else 'Nearly the same as'}: "
                        f"{_short(right.statement, 100)}",
                        related_id=right.id,
                    )
                )

    cutoff = now - timedelta(days=settings.unused_after_days)
    last_used = dict(
        db.execute(
            select(UsageEvent.knowledge_id, func.max(UsageEvent.created_at))
            .where(UsageEvent.workspace_id == scope.workspace_id)
            .group_by(UsageEvent.knowledge_id)
        ).all()
    )
    unused = [
        i
        for i in items
        if aware_utc(i.approved_at) <= cutoff
        and (last_used.get(i.id) is None or aware_utc(last_used[i.id]) <= cutoff)
    ]
    report.unused = [
        GardenItem(
            i.id,
            _short(i.statement),
            f"Last used {_date(last_used[i.id])}" if last_used.get(i.id) else "Never used",
        )
        for i in unused[:limit]
    ]
    return report


def format_gardening(report: GardenReport, base_url: str, workspace_name: str = "") -> str:
    """Plain text for Hermes: one line per item, each with a link that opens it."""
    title = "Weekly Brain gardening" + (f" for {workspace_name}" if workspace_name else "")
    if not report.total():
        return f"{title}\n\nNothing needs attention this week."
    lines = [title, ""]
    for key, label in report.SECTIONS:
        entries: list[GardenItem] = getattr(report, key)
        if not entries:
            continue
        lines.append(f"{label} ({len(entries)})")
        for entry in entries:
            lines.append(f"- {entry.statement}")
            lines.append(f"  {entry.detail}")
            lines.append(f"  {base_url}/#/console/brain?record={entry.knowledge_id}")
        lines.append("")
    return "\n".join(lines).rstrip()


def last_sent(db: Session, workspace_id: str) -> datetime | None:
    value = db.scalar(
        select(func.max(AuditEvent.created_at)).where(
            AuditEvent.workspace_id == workspace_id,
            AuditEvent.action == "routine.gardening_sent",
        )
    )
    return aware_utc(value)


def send_gardening(
    db: Session,
    scope: ReadScope,
    *,
    workspace_name: str = "",
    force: bool = False,
    now: datetime | None = None,
    actor=None,
) -> dict:
    """Send the report through Hermes at most once per `gardening_min_days`."""
    from .messaging import HermesMessenger

    now = now or datetime.now(UTC)
    settings = get_settings()
    previous = last_sent(db, scope.workspace_id)
    if not force and previous and now - previous < timedelta(days=settings.gardening_min_days):
        return {"sent": False, "reason": f"Already sent {previous.date().isoformat()}", "text": ""}
    report = build_gardening(db, scope, now=now)
    text = format_gardening(report, settings.public_base_url.rstrip("/"), workspace_name)
    messenger = HermesMessenger()
    if not messenger.config.configured:
        return {
            "sent": False,
            "reason": "Hermes is not configured (BRAIN_HERMES_URL)",
            "text": text,
        }
    if not messenger.send_routine(text):
        return {"sent": False, "reason": "Hermes did not accept the message", "text": text}
    audit(
        db,
        scope.workspace_id,
        "routine.gardening_sent",
        "workspace",
        scope.workspace_id,
        f"{report.total()} items: {report.counts()}",
        actor=actor,
    )
    db.commit()
    return {"sent": True, "reason": "", "text": text}


def main(argv: list[str] | None = None) -> int:
    from .database import SessionLocal

    args = argv if argv is not None else sys.argv[1:]
    send = "--send" in args
    names = [arg for arg in args if not arg.startswith("--")]
    slug = names[0] if names else "default"
    with SessionLocal() as db:
        workspace = db.scalar(select(Workspace).where(Workspace.slug == slug))
        if workspace is None:
            print(f"No workspace with slug {slug!r}", file=sys.stderr)
            return 2
        scope = ReadScope(workspace.id, "owner")
        if send:
            result = send_gardening(db, scope, workspace_name=workspace.name)
            print(result["text"] or result["reason"])
            return 0 if result["sent"] or result["reason"].startswith("Already sent") else 1
        report = build_gardening(db, scope)
        print(format_gardening(report, get_settings().public_base_url.rstrip("/"), workspace.name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
