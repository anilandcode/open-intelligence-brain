from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def now_utc() -> datetime:
    return datetime.now(UTC)


# Single-workspace deployments address their data by this id, so a Brain that
# was never configured for multiple companies keeps working unchanged.
DEFAULT_WORKSPACE_ID = "ws_default"


class Workspace(Base):
    """A company's Brain. Every other record belongs to exactly one.

    This is the multi-tenancy boundary: sources, proposals and canonical
    knowledge are all scoped to a workspace, and no query may read a row
    without naming the workspace it is allowed to see.
    """

    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class WorkspaceGrant(Base):
    """One principal's access to one workspace.

    A principal is currently an opaque token, not a person: the local demo has
    no identity provider, so this records which shared secret reaches which
    workspace and with which role. Roles are `owner`, `admin` or `member`.
    Read scope inside a workspace is not granted here — it comes from the
    record's own `sensitivity`.
    """

    __tablename__ = "workspace_grants"
    __table_args__ = (
        UniqueConstraint("workspace_id", "principal", name="uq_workspace_grant_principal"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    principal: Mapped[str] = mapped_column(String(120), index=True)
    role: Mapped[str] = mapped_column(String(20), default="member")
    # Scoped grants: a grant can be limited to a specific purpose.
    # None means full access; a string limits what the principal can do.
    scope: Mapped[str | None] = mapped_column(String(80), nullable=True, default=None)
    # Expiring grants: after this time the grant is no longer valid.
    # None means no expiry (the default for local development).
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class User(Base):
    """A human with an account in one or more Brains.

    Identity is an assertion from an identity provider, verified at the boundary
    (`identity.py`) before it becomes a row here. `provider` + `provider_subject`
    is the stable external identity and is the only unique key: an email address
    is display metadata that a provider may reassign, so keying on it would let
    a new person inherit the old person's memberships.

    A `User` is never a credential. It cannot be sent in a header and it cannot
    reach a workspace except through `workspace_members`. That separation from
    `workspace_grants` (machine credentials) is deliberate and is pinned by
    tests: neither class may be substituted for the other.
    """

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("provider", "provider_subject", name="uq_user_provider_subject"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    provider_subject: Mapped[str] = mapped_column(String(120), index=True)
    email: Mapped[str] = mapped_column(String(240), default="")
    display_name: Mapped[str] = mapped_column(String(120), default="")
    # Deactivating a person must revoke access immediately and without hunting
    # through memberships, so the flag is consulted on every membership read.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )


class WorkspaceMember(Base):
    """A person's access to one workspace, and the role they hold there.

    The human counterpart to `workspace_grants`, which records a machine
    credential. Kept as a separate table on purpose: a token is not a person and
    a person is not a token, so an audit trail that conflated them could never
    say who acted. Roles are `owner`, `admin` or `member`, and the sensitivity
    ceiling for each is the same rule `workspace_grants` uses.
    """

    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member_user"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="member")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), index=True, default=DEFAULT_WORKSPACE_ID
    )
    title: Mapped[str] = mapped_column(String(240))
    kind: Mapped[str] = mapped_column(String(40), default="note")
    sensitivity: Mapped[str] = mapped_column(String(40), default="private")
    content: Mapped[str] = mapped_column(Text)
    # The engine's own document id for this source's latest content. Facts are
    # pulled per document, so the link has to be stored, not guessed: matching
    # a derived claim to the wrong source would corrupt the provenance chain.
    engine_document_id: Mapped[str] = mapped_column(String(64), default="")
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
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), index=True, default=DEFAULT_WORKSPACE_ID
    )
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    statement: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text, default="")
    source_excerpt: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="proposed", index=True)
    # Set only on engine-derived proposals: the review decision is echoed back
    # to the engine by memory id so its ranking agrees with ours.
    engine_memory_id: Mapped[str] = mapped_column(String(64), default="")
    critic_notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    source: Mapped[Source] = relationship(back_populates="proposals")


class ProposalEvidence(Base):
    """The edge that makes a proposal checkable.

    `source_span_id` is nullable because a derived proposal has no single
    excerpt: the engine inferred a fact across memories rather than quoting one.
    The version edge is still mandatory, so a proposal always points at the
    exact immutable bytes it came from — evidence is required, a span is not.
    """

    __tablename__ = "proposal_evidence"
    __table_args__ = ()

    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), primary_key=True)
    source_version_id: Mapped[str] = mapped_column(ForeignKey("source_versions.id"), index=True)
    source_span_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_spans.id"), nullable=True, index=True
    )


class Knowledge(Base):
    __tablename__ = "knowledge"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), index=True, default=DEFAULT_WORKSPACE_ID
    )
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
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), index=True, default=DEFAULT_WORKSPACE_ID
    )
    action: Mapped[str] = mapped_column(String(80), index=True)
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
