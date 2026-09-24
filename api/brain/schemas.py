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
    current_version: int = 1
    content_hash: str = ""


class SourceVersionCreate(BaseModel):
    content: str = Field(min_length=20, max_length=100_000)
    change_note: str = Field(min_length=3, max_length=1_000)


class SourceVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    source_id: str
    version: int
    content_hash: str
    content: str
    parser_version: str
    change_note: str
    created_at: datetime
    span_count: int = 0
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
    revision_count: int = 1
    stale: bool = False
    conflict_ids: list[str] = Field(default_factory=list)


class KnowledgeRevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    knowledge_id: str
    revision: int
    statement: str
    rationale: str
    source_id: str
    source_version_id: str
    source_span_id: str | None
    source_excerpt: str
    change_note: str
    approved_at: datetime


class SupersedeRequest(BaseModel):
    statement: str = Field(min_length=3, max_length=5_000)
    rationale: str = Field(default="", max_length=10_000)
    change_note: str = Field(min_length=3, max_length=1_000)


class IntegrityIssue(BaseModel):
    kind: str
    knowledge_id: str
    related_id: str | None = None
    detail: str


class IntegrityRead(BaseModel):
    stale_count: int
    conflict_count: int
    issues: list[IntegrityIssue]


class DeletionPreview(BaseModel):
    source_id: str
    versions: int
    spans: int
    proposals: int
    canonical_items: int
    audit_events: int
    blocked: bool
    reason: str


class RestoreRequest(BaseModel):
    backup: dict
    confirm_empty_workspace: bool = False


class RestorePreview(BaseModel):
    schema_version: int
    valid: bool
    empty_workspace: bool
    counts: dict[str, int]
    blockers: list[str]


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
