"""Event intake and turn orchestration tables.

The Brain used to have one entrance: a human pasted a document and the engine
proposed facts from it. This module adds the other entrance — an event arrives
from a channel, triage turns it into one of three actions, and the action runs as
a turn that can be steered, stopped, and resumed.

Two rules shape the schema:

* A turn records what it did; it never writes canonical knowledge. Proposed
  writes stop at the existing approval gate, so adding an event loop cannot
  weaken the one guarantee the product already had.
* Every root table carries `workspace_id`, like `sources` and `proposals`, so an
  event from one company's channel can never be triaged against another
  company's Brain.
"""

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import DEFAULT_WORKSPACE_ID


def now_utc() -> datetime:
    return datetime.now(UTC)


class BrainEvent(Base):
    """One inbound message, already classified.

    The raw text is kept because it is the evidence for the triage decision, but
    the classification is stored next to it rather than recomputed: a later
    policy change must not silently re-label history.
    """

    __tablename__ = "brain_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), index=True, default=DEFAULT_WORKSPACE_ID
    )
    channel: Mapped[str] = mapped_column(String(120), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    author: Mapped[str] = mapped_column(String(120), default="")
    text: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Turn(Base):
    """A resumable unit of agency.

    State lives in the row, not in a process, so a turn suspended for approval
    survives a restart and resumes from `checkpoint` instead of from memory.
    `superseded_by` names the event that overtook this one, which is what makes
    "the newer message wins" auditable rather than implicit.
    """

    __tablename__ = "turns"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), index=True, default=DEFAULT_WORKSPACE_ID
    )
    event_id: Mapped[str | None] = mapped_column(
        ForeignKey("brain_events.id"), index=True, nullable=True
    )
    channel: Mapped[str] = mapped_column(String(120), index=True)
    action: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(Text, default="")
    instructions: Mapped[str] = mapped_column(Text, default="")
    step_budget: Mapped[int] = mapped_column(Integer, default=0)
    steps_used: Mapped[int] = mapped_column(Integer, default=0)
    checkpoint: Mapped[str] = mapped_column(Text, default="")
    suspension: Mapped[str] = mapped_column(Text, default="")
    superseded_by: Mapped[str] = mapped_column(String(32), default="")
    stop_reason: Mapped[str] = mapped_column(String(40), default="")
    leased_by: Mapped[str | None] = mapped_column(String(60), nullable=True, default=None)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )


class TurnStep(Base):
    """One recorded step, in order.

    The transcript is the turn's audit trail: a step is appended before the next
    one is attempted, so a turn that dies mid-flight leaves an accurate account
    of how far it got.
    """

    __tablename__ = "turn_steps"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    turn_id: Mapped[str] = mapped_column(ForeignKey("turns.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    tool: Mapped[str] = mapped_column(String(60), default="")
    kind: Mapped[str] = mapped_column(String(24), default="tool")
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ProactivitySetting(Base):
    """How much a channel is allowed to interrupt.

    One row per channel, so turning a channel down does not turn the Brain down:
    a channel set to `off` still records what arrived, it just never acts on it.
    """

    __tablename__ = "proactivity_settings"
    __table_args__ = (UniqueConstraint("workspace_id", "channel", name="uq_proactivity_channel"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), index=True, default=DEFAULT_WORKSPACE_ID
    )
    channel: Mapped[str] = mapped_column(String(120), index=True)
    mode: Mapped[str] = mapped_column(String(24), default="mentions")
    min_confidence: Mapped[float] = mapped_column(Float, default=0.6)
    answer_threshold: Mapped[float] = mapped_column(Float, default=0.75)
    allow_investigate: Mapped[bool] = mapped_column(Boolean, default=True)
    react: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )
