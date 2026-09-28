from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .triage import TRIAGE_VERSION


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


class EngineRead(BaseModel):
    """Which extraction engine answered, and why not a better one.

    Surfaced because a silent fallback to local extraction is how a deployment
    ends up believing it is running on a model when it is not.
    """

    name: str
    available: bool
    detail: str
    container_tag: str = ""
    # Reachable but not working. An engine with no model provider configured
    # accepts content and extracts nothing, which is indistinguishable from
    # success at the HTTP layer and so has to be reported separately.
    degraded: bool = False


class OverviewRead(BaseModel):
    sources: int
    proposals: int
    canonical: int
    pending_reviews: int
    recent_activity: list[dict]
    engine: EngineRead


class WorkspaceCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=64, pattern="^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=2, max_length=120)


class WorkspaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    slug: str
    name: str
    created_at: datetime
class EventCreate(BaseModel):
    """One inbound message, as a channel or an agent would report it.

    `model_output` is optional and private: it is the harness's own reading of
    the event, carried so triage can be tested against a model reply without
    that reply ever becoming the decision itself.
    """

    channel: str = Field(default="#general", min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=8_000)
    author: str = Field(default="", max_length=120)
    addressed: bool = False
    is_bot: bool = False
    external_id: str = Field(default="", max_length=120)
    model_output: str | None = Field(default=None, max_length=4_000)
    evidence_strength: float = Field(default=0.0, ge=0.0, le=1.0)


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    channel: str
    kind: str
    author: str
    text: str
    external_id: str
    created_at: datetime


class TriageRead(BaseModel):
    """The decision, plus the rule that produced it.

    `reason` is assembled from parsed fields only. `private_raw` stays on the
    service object and is deliberately not part of this response.
    """

    action: str
    confidence: float
    reason: str
    source: str
    kind: str
    react: str = ""
    version: str = TRIAGE_VERSION


class TurnStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    ordinal: int
    tool: str
    kind: str
    summary: str
    created_at: datetime


class TurnRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    event_id: str | None = None
    channel: str
    action: str
    status: str
    confidence: float
    reason: str
    instructions: str = ""
    step_budget: int
    steps_used: int
    stop_reason: str = ""
    superseded_by: str = ""
    created_at: datetime
    updated_at: datetime


class TurnDetail(TurnRead):
    """A turn with its transcript, its plan, and its allowed tools.

    The tool set is returned rather than implied so a client can render the
    budget honestly and never offer an action the server would refuse.
    """

    steps: list[TurnStepRead] = Field(default_factory=list)
    plan: list[str] = Field(default_factory=list)
    active_tools: list[str] = Field(default_factory=list)


class EventIntake(BaseModel):
    event: EventRead
    turn: TurnRead
    triage: TriageRead
    superseded: list[str] = Field(default_factory=list)


class StepRequest(BaseModel):
    tool: str = Field(min_length=3, max_length=60)
    summary: str = Field(min_length=3, max_length=1_000)


class StepResponse(BaseModel):
    turn: TurnRead
    step: TurnStepRead
    exhausted: bool = False


class SteerRequest(BaseModel):
    note: str = Field(min_length=3, max_length=2_000)


class SuspendRequest(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=3, max_length=600)


class ResumeRequest(BaseModel):
    approved: bool
    note: str = Field(default="", max_length=1_000)


class StopRequest(BaseModel):
    reason: str = Field(default="", max_length=40)


class ProactivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    channel: str
    mode: str
    min_confidence: float
    answer_threshold: float
    allow_investigate: bool
    react: bool
    updated_at: datetime


class ProactivityUpdate(BaseModel):
    channel: str = Field(min_length=1, max_length=120)
    mode: str = Field(default="mentions", pattern="^(off|mentions|contextual|proactive)$")
    min_confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    answer_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    allow_investigate: bool = True
    react: bool = True
