from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
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


class SourceVersion(Base):
    __tablename__ = "source_versions"
    __table_args__ = (
        UniqueConstraint("source_id", "version", name="uq_source_version_number"),
        UniqueConstraint("source_id", "content_hash", name="uq_source_version_hash"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    content: Mapped[str] = mapped_column(Text)
    parser_version: Mapped[str] = mapped_column(String(40), default="deterministic-v1")
    change_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class SourceSpan(Base):
    __tablename__ = "source_spans"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_version_id: Mapped[str] = mapped_column(ForeignKey("source_versions.id"), index=True)
    start_offset: Mapped[int] = mapped_column(Integer)
    end_offset: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    span_hash: Mapped[str] = mapped_column(String(64), index=True)
    speaker: Mapped[str | None] = mapped_column(String(160), nullable=True)


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


class ProposalEvidence(Base):
    __tablename__ = "proposal_evidence"

    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), primary_key=True)
    source_version_id: Mapped[str] = mapped_column(ForeignKey("source_versions.id"), index=True)
    source_span_id: Mapped[str] = mapped_column(ForeignKey("source_spans.id"), index=True)


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


class KnowledgeRevision(Base):
    __tablename__ = "knowledge_revisions"
    __table_args__ = (
        UniqueConstraint("knowledge_id", "revision", name="uq_knowledge_revision_number"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    knowledge_id: Mapped[str] = mapped_column(ForeignKey("knowledge.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    statement: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text, default="")
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    source_version_id: Mapped[str] = mapped_column(ForeignKey("source_versions.id"), index=True)
    source_span_id: Mapped[str | None] = mapped_column(ForeignKey("source_spans.id"), nullable=True)
    source_excerpt: Mapped[str] = mapped_column(Text)
    change_note: Mapped[str] = mapped_column(Text, default="")
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
