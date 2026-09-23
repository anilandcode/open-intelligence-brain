from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SourceCreate(BaseModel):
    title: str = Field(min_length=3, max_length=240)
    kind: str = Field(default="note", pattern="^(note|research|interview|decision)$")
    sensitivity: str = Field(default="private", pattern="^(private|internal|public)$")
    content: str = Field(min_length=20, max_length=100_000)


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    kind: str
    sensitivity: str
    content: str
    created_at: datetime
    proposal_count: int = 0


class ProposalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    source_id: str
    source_title: str = ""
    type: str
    statement: str
    rationale: str
    source_excerpt: str
    status: str
    created_at: datetime


class ApprovalRequest(BaseModel):
    statement: str | None = Field(default=None, min_length=3, max_length=5_000)
    rationale: str | None = Field(default=None, max_length=10_000)


class RejectRequest(BaseModel):
    reason: str = Field(default="Not ready for canonical use", min_length=3, max_length=1_000)


class KnowledgeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    proposal_id: str
    source_id: str
    source_title: str = ""
    type: str
    statement: str
    rationale: str
    source_excerpt: str
    status: str
    version: int
    approved_at: datetime


class ChatRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2_000)


class Citation(BaseModel):
    knowledge_id: str
    source_id: str
    source_title: str
    excerpt: str


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    grounded: bool


class OverviewRead(BaseModel):
    sources: int
    proposals: int
    canonical: int
    pending_reviews: int
    recent_activity: list[dict]
