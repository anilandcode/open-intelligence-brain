from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def now_utc() -> datetime:
    return datetime.now(UTC)


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(240))
    kind: Mapped[str] = mapped_column(String(40), default="note")
    sensitivity: Mapped[str] = mapped_column(String(40), default="private")
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    proposals: Mapped[list["Proposal"]] = relationship(back_populates="source")


class Proposal(Base):
    __tablename__ = "proposals"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    statement: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text, default="")
    source_excerpt: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="proposed", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    source: Mapped[Source] = relationship(back_populates="proposals")


class Knowledge(Base):
    __tablename__ = "knowledge"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), unique=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    type: Mapped[str] = mapped_column(String(40), index=True)
    statement: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text, default="")
    source_excerpt: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="canonical", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
