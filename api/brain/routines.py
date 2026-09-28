"""Daily routines — the Brain talks to you.

A routine is a scheduled check-in. The Brain looks at what needs attention
(pending proposals, stale knowledge, new conflicts, recent activity) and
sends a summary through the configured channel.

Routines are timezone-aware and handle missed runs gracefully — if you
skip a day, the next run catches up with everything that accumulated.

This is what makes the Brain go from "a place to store knowledge" to
"a place that tells you what to do next."
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .access import ReadScope
from .models import Knowledge, Proposal, Source
from .services import integrity_snapshot, knowledge_is_stale

logger = logging.getLogger("brain.routines")


@dataclass(frozen=True)
class RoutineDigest:
    """What the Brain wants to tell you."""

    pending_proposals: int = 0
    stale_knowledge: int = 0
    conflict_count: int = 0
    recent_approvals: int = 0
    recent_sources: int = 0
    top_proposals: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: str = ""

    def is_empty(self) -> bool:
        return (
            self.pending_proposals == 0
            and self.stale_knowledge == 0
            and self.conflict_count == 0
            and self.recent_approvals == 0
            and self.recent_sources == 0
        )


class DeliveryChannel(Protocol):
    """Where the routine digest goes."""

    def send(self, message: str, channel: str) -> bool: ...


class LogDelivery:
    """Default delivery — logs the digest. Replace with Hermes/Slack/email."""

    name = "log"

    def send(self, message: str, channel: str) -> bool:
        logger.info("Routine digest [%s]:\n%s", channel, message)
        return True


class HermesDelivery:
    """Deliver through Hermes messaging."""

    name = "hermes"

    def __init__(self, api_url: str | None = None):
        self.api_url = api_url

    def send(self, message: str, channel: str) -> bool:
        if not self.api_url:
            logger.info("Hermes delivery (local):\n%s", message)
            return True
        try:
            import httpx

            httpx.post(
                f"{self.api_url}/api/v1/send",
                json={"channel": channel, "message": message},
                timeout=10,
            )
            return True
        except Exception as exc:
            logger.warning("Hermes delivery failed: %s", exc)
            return False


def build_digest(db: Session, scope: ReadScope, since_hours: int = 24) -> RoutineDigest:
    """Build the morning digest from the Brain's current state."""
    since = datetime.now(UTC) - timedelta(hours=since_hours)

    # Pending proposals
    pending = (
        db.scalar(
            select(func.count(Proposal.id)).where(
                Proposal.workspace_id == scope.workspace_id,
                Proposal.status == "proposed",
            )
        )
        or 0
    )

    # Stale knowledge
    items = list(
        db.scalars(
            select(Knowledge).where(
                Knowledge.workspace_id == scope.workspace_id,
                Knowledge.status == "canonical",
            )
        ).all()
    )
    stale = sum(1 for item in items if knowledge_is_stale(db, item))

    # Conflicts
    integrity = integrity_snapshot(db, scope)
    conflicts = integrity.get("conflict_count", 0)
    warnings = [issue["detail"] for issue in integrity.get("issues", [])[:5]]

    # Recent activity
    approvals = (
        db.scalar(
            select(func.count(Knowledge.id)).where(
                Knowledge.workspace_id == scope.workspace_id,
                Knowledge.approved_at >= since,
            )
        )
        or 0
    )

    sources = (
        db.scalar(
            select(func.count(Source.id)).where(
                Source.workspace_id == scope.workspace_id,
                Source.created_at >= since,
            )
        )
        or 0
    )

    # Top pending proposals (most recent 3)
    top = list(
        db.scalars(
            select(Proposal)
            .where(
                Proposal.workspace_id == scope.workspace_id,
                Proposal.status == "proposed",
            )
            .order_by(Proposal.created_at.desc())
            .limit(3)
        ).all()
    )

    top_proposals = [{"id": p.id, "type": p.type, "statement": p.statement[:120]} for p in top]

    # Build summary
    parts = []
    if pending:
        parts.append(f"📋 {pending} proposal{'s' if pending != 1 else ''} waiting for review")
    if stale:
        parts.append(f"⚠️ {stale} knowledge item{'s' if stale != 1 else ''} may be stale")
    if conflicts:
        parts.append(f"🔴 {conflicts} potential conflict{'s' if conflicts != 1 else ''}")
    if approvals:
        s = "s" if approvals != 1 else ""
        parts.append(f"✅ {approvals} approval{s} in the last {since_hours}h")
    if sources:
        parts.append(f"📥 {sources} new source{'s' if sources != 1 else ''} captured")

    if not parts:
        summary = "✨ Nothing needs attention. Your Brain is healthy."
    else:
        summary = "Good morning! Here's what needs your attention:\n" + "\n".join(
            f"  {p}" for p in parts
        )

    return RoutineDigest(
        pending_proposals=pending,
        stale_knowledge=stale,
        conflict_count=conflicts,
        recent_approvals=approvals,
        recent_sources=sources,
        top_proposals=top_proposals,
        warnings=warnings,
        summary=summary,
    )


def format_digest(digest: RoutineDigest, workspace_name: str = "") -> str:
    """Format the digest for delivery."""
    header = f"🧠 Brain Update{' — ' + workspace_name if workspace_name else ''}"
    body = digest.summary
    footer = ""

    if digest.top_proposals:
        footer += "\n\nTop proposals to review:"
        for p in digest.top_proposals:
            footer += f"\n  [{p['type']}] {p['statement']}"

    if digest.warnings:
        footer += "\n\nWarnings:"
        for w in digest.warnings:
            footer += f"\n  • {w}"

    footer += "\n\nOpen your Brain: http://localhost:5173"
    return f"{header}\n{'─' * 40}\n{body}{footer}"
