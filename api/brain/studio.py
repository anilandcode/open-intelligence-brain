"""Interview sessions and draft builder for Intelligence Studio.

Interviews are structured conversations that extract knowledge from experts.
Each session has a topic, a person, and a set of questions. Responses are
captured as source material and proposals are extracted automatically.

Drafts are assembled from approved knowledge atoms. Each section of a draft
cites the knowledge items it draws on, so every claim in the output traces
back to approved, reviewed intelligence.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _now() -> datetime:
    return datetime.now(UTC)


class InterviewSession(Base):
    """One guided interview conversation."""

    __tablename__ = "interview_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    title: Mapped[str] = mapped_column(String(240))
    topic: Mapped[str] = mapped_column(Text, default="")
    person: Mapped[str] = mapped_column(String(160), default="")
    audience: Mapped[str] = mapped_column(String(160), default="")
    outcome: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="drafting")  # drafting, active, completed
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    questions: Mapped[list["InterviewQuestion"]] = relationship(
        back_populates="session", order_by="InterviewQuestion.ordinal"
    )


class InterviewQuestion(Base):
    """One question in a guided interview."""

    __tablename__ = "interview_questions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("interview_sessions.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    question_text: Mapped[str] = mapped_column(Text)
    response_text: Mapped[str] = mapped_column(Text, default="")
    extracted: Mapped[bool] = mapped_column(default=False)  # True after proposals created
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    session: Mapped["InterviewSession"] = relationship(back_populates="questions")


class Draft(Base):
    """One output document assembled from approved knowledge."""

    __tablename__ = "drafts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    title: Mapped[str] = mapped_column(String(240))
    intent: Mapped[str] = mapped_column(String(40), default="brief")  # brief, article, agent, questions
    audience: Mapped[str] = mapped_column(String(160), default="")
    status: Mapped[str] = mapped_column(String(30), default="drafting")  # drafting, published
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    sections: Mapped[list["DraftSection"]] = relationship(
        back_populates="draft", order_by="DraftSection.ordinal"
    )


class DraftSection(Base):
    """One section of a draft document."""

    __tablename__ = "draft_sections"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    draft_id: Mapped[str] = mapped_column(ForeignKey("drafts.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(240), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    draft: Mapped["Draft"] = relationship(back_populates="sections")
    citations: Mapped[list["DraftCitation"]] = relationship(back_populates="section")


class DraftCitation(Base):
    """A link from a draft section to an approved knowledge item."""

    __tablename__ = "draft_citations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    section_id: Mapped[str] = mapped_column(ForeignKey("draft_sections.id"), index=True)
    knowledge_id: Mapped[str] = mapped_column(ForeignKey("knowledge.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    section: Mapped["DraftSection"] = relationship(back_populates="citations")