"""Schemas for Intelligence Studio — interviews and drafts."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# --- Interview sessions ---

class InterviewSessionCreate(BaseModel):
    title: str = Field(min_length=3, max_length=240)
    topic: str = Field(default="", max_length=2_000)
    person: str = Field(default="", max_length=160)
    audience: str = Field(default="", max_length=160)
    outcome: str = Field(default="", max_length=2_000)


class InterviewQuestionCreate(BaseModel):
    question_text: str = Field(min_length=3, max_length=2_000)


class InterviewResponseSubmit(BaseModel):
    response_text: str = Field(min_length=1, max_length=50_000)


class InterviewQuestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    session_id: str
    ordinal: int
    question_text: str
    response_text: str
    extracted: bool
    created_at: datetime


class InterviewSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    workspace_id: str
    title: str
    topic: str
    person: str
    audience: str
    outcome: str
    status: str
    source_id: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    question_count: int = 0
    response_count: int = 0
    extracted_count: int = 0


class InterviewSessionDetail(InterviewSessionRead):
    questions: list[InterviewQuestionRead] = Field(default_factory=list)


# --- Drafts ---

class DraftCreate(BaseModel):
    title: str = Field(min_length=3, max_length=240)
    intent: str = Field(default="brief", pattern="^(brief|article|agent|questions)$")
    audience: str = Field(default="", max_length=160)


class DraftSectionCreate(BaseModel):
    title: str = Field(default="", max_length=240)
    content: str = Field(default="", max_length=50_000)
    knowledge_ids: list[str] = Field(default_factory=list)


class DraftSectionUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=240)
    content: str | None = Field(default=None, max_length=50_000)
    knowledge_ids: list[str] | None = None


class DraftCitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    section_id: str
    knowledge_id: str
    created_at: datetime


class DraftSectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    draft_id: str
    ordinal: int
    title: str
    content: str
    created_at: datetime
    citations: list[DraftCitationRead] = Field(default_factory=list)
    knowledge_items: list[dict] = Field(default_factory=list)


class DraftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    workspace_id: str
    title: str
    intent: str
    audience: str
    status: str
    created_at: datetime
    updated_at: datetime
    section_count: int = 0
    citation_count: int = 0


class DraftDetail(DraftRead):
    sections: list[DraftSectionRead] = Field(default_factory=list)


class DraftAssembleRequest(BaseModel):
    """Assemble a draft from approved knowledge atoms."""
    title: str = Field(min_length=3, max_length=240)
    intent: str = Field(default="brief", pattern="^(brief|article|agent|questions)$")
    audience: str = Field(default="", max_length=160)
    knowledge_ids: list[str] = Field(min_length=1)
    include_excerpts: bool = True