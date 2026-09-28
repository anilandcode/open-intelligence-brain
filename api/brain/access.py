"""Workspace resolution and scoping.

A principal arrives as the `X-Brain-Token` header, a workspace arrives as the
optional `X-Brain-Workspace` header, and every read and write is filtered by the
resolved pair. A principal with no grant sees nothing.

The scoping rule is deliberately narrow: `workspace_id` is stored on the root
tables (sources, proposals, knowledge, audit_events) and the child tables are
reached through their parent. Duplicating the column on children would let a
row disagree with its own parent after a bad write.
"""

from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    DEFAULT_WORKSPACE_ID,
    AuditEvent,
    Knowledge,
    Proposal,
    Source,
    Workspace,
    WorkspaceGrant,
    new_id,
)


class AccessDenied(Exception):
    """The principal may not act on this workspace."""


# Sensitivity is an ordered ladder: a role that may read `internal` may also read
# `public`. It is stored on the source, so knowledge and proposals reach it
# through `source_id` — the same rule the provenance chain already uses, which
# keeps a child row from disagreeing with its parent about how private it is.
SENSITIVITY_RANK = {"public": 0, "internal": 1, "private": 2}

# A member does not administer the workspace, so private material stays out of
# reach. Owners and admins review that material by design — the approval gate
# cannot function if the reviewer cannot read the excerpt being approved.
_MEMBER_CEILING = "internal"
_ADMIN_CEILING = "private"


def allowed_sensitivities(role: str) -> set[str]:
    """The sensitivity values a role may read inside a workspace."""
    ceiling = _ADMIN_CEILING if role in ("owner", "admin") else _MEMBER_CEILING
    return {value for value, rank in SENSITIVITY_RANK.items() if rank <= SENSITIVITY_RANK[ceiling]}


def visible_source_ids(role: str):
    """A subquery of source ids this role may read, for use in a WHERE clause."""
    return select(Source.id).where(Source.sensitivity.in_(allowed_sensitivities(role)))


class ReadScope:
    """The workspace a caller may read plus the sensitivities their role allows.

    Collection reads cannot go through `require_in_workspace`, which is keyed on
    a single record id. This carries the same decision into a `WHERE` clause so
    a list can never surface a row the single-record path would have refused.
    It is deliberately the only way services read rows: passing a bare
    `workspace_id` string is what let `sensitivity` sit unenforced.
    """

    def __init__(self, workspace_id: str, role: str) -> None:
        self.workspace_id = workspace_id
        self.role = role
        self.permitted = allowed_sensitivities(role)

    @classmethod
    def of(cls, access: "WorkspaceAccess") -> "ReadScope":
        return cls(access.workspace_id, access.role)

    def may_read(self, sensitivity: str) -> bool:
        return sensitivity in self.permitted

    def source_ids(self):
        """Subquery of readable source ids. Joins against the source table."""
        return select(Source.id).where(
            Source.workspace_id == self.workspace_id,
            Source.sensitivity.in_(self.permitted),
        )

    def apply(self, stmt, model):
        """Narrow a select to the rows this scope may read.

        `Source` carries `sensitivity` directly. `Knowledge` and `Proposal` reach
        it through `source_id`; the child tables (`SourceVersion`, `SourceSpan`,
        `KnowledgeRevision`) are reached through their own parent, so the caller
        must scope those by an id list that came from a scoped parent rather than
        from this method.
        """
        if model is Source:
            return stmt.where(
                Source.workspace_id == self.workspace_id,
                Source.sensitivity.in_(self.permitted),
            )
        if model is Knowledge:
            return stmt.where(
                Knowledge.workspace_id == self.workspace_id,
                Knowledge.source_id.in_(self.source_ids()),
            )
        if model is Proposal:
            return stmt.where(
                Proposal.workspace_id == self.workspace_id,
                Proposal.source_id.in_(self.source_ids()),
            )
        return stmt.where(model.workspace_id == self.workspace_id)


@dataclass(frozen=True)
class WorkspaceAccess:
    """A resolved principal/workspace pair and the role it holds there."""

    workspace: Workspace
    principal: str
    role: str

    @property
    def workspace_id(self) -> str:
        return self.workspace.id

    @property
    def can_administer(self) -> bool:
        return self.role in ("owner", "admin")

    @property
    def permitted(self) -> set[str]:
        return allowed_sensitivities(self.role)

    def can_read_source(self, source_id: str, sensitivity: str) -> bool:
        return sensitivity in self.permitted


def require_in_workspace(db: Session, access: WorkspaceAccess, model, record_id: str):
    """Load a record only if the caller may both see its workspace and read it.

    Two independent checks, because workspace membership is not permission. A
    record in another workspace is reported as 404 rather than 403, because
    confirming its existence would leak it. A record inside the caller's own
    workspace but above the caller's sensitivity ceiling is also 404, so a
    member cannot distinguish "no such record" from "not yours to read" — which
    is what makes the check worth having at all.
    """
    record = db.get(model, record_id)
    if record is None or record.workspace_id != access.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if not _readable(access, db, model, record):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return record


def _readable(access: WorkspaceAccess, db: Session, model, record) -> bool:
    """Whether the caller may read a record they already own in their workspace.

    `sensitivity` is stored only on the source, so every other record reaches it
    through `source_id`. A record with no reachable source cannot be proven
    visible, and is refused.
    """
    if model is Source:
        return access.can_read_source(record.id, record.sensitivity)
    source_id = getattr(record, "source_id", None)
    if source_id is None:
        return False
    sensitivity = db.scalar(select(Source.sensitivity).where(Source.id == source_id))
    if sensitivity is None:
        return False
    return access.can_read_source(source_id, sensitivity)


def ensure_default_workspace(db: Session) -> Workspace:
    """Create the single-workspace landing zone if it is missing.

    A Brain that is never configured for multiple companies must keep working
    exactly as it did before workspaces existed, so every record created without
    an explicit workspace lands here.
    """
    workspace = db.get(Workspace, DEFAULT_WORKSPACE_ID)
    if workspace is None:
        workspace = Workspace(id=DEFAULT_WORKSPACE_ID, slug="default", name="My workspace")
        db.add(workspace)
        db.flush()
    return workspace


def resolve_workspace(
    db: Session, token: str, requested_slug: str | None = None
) -> WorkspaceAccess:
    """Turn a token plus an optional workspace slug into a scoped access object.

    With a single grant the workspace is implied and the header is optional. With
    several grants the caller must say which workspace it means, so a request
    can never silently act on the wrong company's Brain.
    """
    if not token:
        raise AccessDenied("Invalid Brain token")
    grants = list(
        db.scalars(select(WorkspaceGrant).where(WorkspaceGrant.principal == token)).all()
    )
    if not grants:
        raise AccessDenied("Invalid Brain token")
    if requested_slug:
        # The header names a slug; grants key on the workspace id, so resolve one
        # to the other before comparing.
        workspace = db.scalar(select(Workspace).where(Workspace.slug == requested_slug))
        if workspace is None:
            raise AccessDenied("Unknown workspace")
        target = next(
            (grant for grant in grants if grant.workspace_id == workspace.id), None
        )
        if target is None:
            raise AccessDenied("This Brain token has no access to that workspace")
    elif len(grants) == 1:
        target = grants[0]
    else:
        raise AccessDenied(
            "This token reaches several workspaces; send the X-Brain-Workspace header"
        )
    workspace = db.get(Workspace, target.workspace_id)
    if workspace is None:
        raise AccessDenied("Unknown workspace")
    return WorkspaceAccess(workspace=workspace, principal=token, role=target.role)


def grant_workspace(
    db: Session, workspace: Workspace | None, principal: str, role: str = "member"
) -> WorkspaceGrant:
    """Give a principal access to a workspace, replacing any existing grant."""
    if workspace is None:
        raise ValueError("Cannot grant access to a workspace that does not exist")
    existing = db.scalar(
        select(WorkspaceGrant).where(
            WorkspaceGrant.workspace_id == workspace.id,
            WorkspaceGrant.principal == principal,
        )
    )
    if existing is not None:
        existing.role = role
        return existing
    grant = WorkspaceGrant(
        id=new_id("wsg"),
        workspace_id=workspace.id,
        principal=principal,
        role=role,
    )
    db.add(grant)
    db.flush()
    return grant


def audit_access(db: Session, access: WorkspaceAccess, action: str, detail: str = "") -> None:
    """Record a workspace-level event in the same stream as record events."""
    db.add(
        AuditEvent(
            id=new_id("evt"),
            workspace_id=access.workspace_id,
            action=action,
            resource_type="workspace",
            resource_id=access.workspace_id,
            detail=detail,
        )
    )


def workspace_counts(db: Session, scope: ReadScope) -> dict[str, int]:
    """Per-workspace totals, filtered by what this scope may read.

    Every count is scoped, never global, and a member's totals exclude private
    material — a count is a read, and leaking the existence of private rows
    through the number alone would defeat the check.
    """
    return {
        "sources": db.scalar(
            scope.apply(select(func.count(Source.id)), Source)
        )
        or 0,
        "proposals": db.scalar(
            scope.apply(select(func.count(Proposal.id)), Proposal)
        )
        or 0,
        "canonical": db.scalar(
            scope.apply(select(func.count(Knowledge.id)), Knowledge)
        )
        or 0,
        "pending_reviews": db.scalar(
            scope.apply(
                select(func.count(Proposal.id)).where(Proposal.status == "proposed"),
                Proposal,
            )
        )
        or 0,
    }
