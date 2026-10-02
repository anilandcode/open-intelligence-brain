"""Sign-in routes. Identity in, a session out — and nothing else.

Three routes, deliberately few:

- `POST /api/v1/auth/login`  exchange a provider credential for a session
- `POST /api/v1/auth/logout` end the caller's own session
- `GET  /api/v1/auth/me`     who the caller is, and what they are a member of

None of these grant reach to a workspace. A login creates identity and a
session; `workspace_members` still decides what that session can see. That
split is the point: inviting someone and accepting their sign-in are different
acts and belong to different people.

The raw session secret appears exactly once, in the login response. It is
never in `me`, never in a listing, and never in an audit detail.
"""

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import Workspace
from .database import get_db
from .identity import IdentityError
from .models import User, UserSession, WorkspaceMember
from .sessions import revoke_session, sign_in_with_credential

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """A provider credential. Never a user id, email, or role.

    The field is named `credential` so nothing at the edge can be mistaken for
    a claim about who the caller is.
    """

    credential: str = Field(min_length=1, max_length=2048)


class UserRead(BaseModel):
    """A person. Not a credential — there is no field here that could be sent
    back as one."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: str
    email: str
    display_name: str


class MembershipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    workspace_id: str
    workspace_slug: str
    workspace_name: str
    role: str


class LoginResponse(BaseModel):
    """The ONLY place a raw session secret is ever returned."""

    session_token: str
    expires_at: str
    user: UserRead


class MeResponse(BaseModel):
    user: UserRead
    memberships: list[MembershipRead]


class AuthStatusRead(BaseModel):
    """Public, unauthenticated: which human sign-in path this deployment offers.

    Never includes claims, secrets, or project numbers beyond what the client
    already needs to know whether to show a sign-in form.
    """

    sign_in_available: bool
    provider: str | None = None


@router.get("/status", response_model=AuthStatusRead)
def auth_status():
    """Whether a human can sign in on this deployment."""
    from .identity import get_identity_provider

    try:
        provider = get_identity_provider()
    except ValueError:
        # Misconfigured provider is not "available" to the browser; ops must fix it.
        return AuthStatusRead(sign_in_available=False, provider=None)
    if provider is None:
        return AuthStatusRead(sign_in_available=False, provider=None)
    return AuthStatusRead(sign_in_available=True, provider=provider.name)


@router.post("/login", response_model=LoginResponse, status_code=status.HTTP_200_OK)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Exchange a verified provider credential for a session.

    A failed credential returns the same 401 and the same message whether the
    account is unknown, the credential is wrong, or no provider is configured —
    three different causes, one indistinguishable answer, so the route cannot be
    used to enumerate people or to detect which providers a deployment has.
    """
    try:
        raw, user = sign_in_with_credential(
            db,
            payload.credential,
            user_agent=request.headers.get("user-agent", ""),
        )
    except IdentityError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    # Login logging: the UserSession row already records who / when / from what
    # client; this adds an audit-trail entry so sign-ins sit alongside every other
    # operation. A login grants identity ONLY — reach stays with membership (the
    # invariant: sessions prove who, memberships grant reach). The first owner is
    # claimed explicitly via POST /auth/bootstrap, never granted by a login.
    from .identity import membership_access
    from .models import DEFAULT_WORKSPACE_ID, Workspace
    from .services import audit

    workspace = db.get(Workspace, DEFAULT_WORKSPACE_ID)
    if workspace is not None:
        access = membership_access(db, user, workspace)
        audit(
            db,
            workspace.id,
            "auth.login",
            "user",
            user.id,
            f"Signed in as {user.email or user.display_name or user.id}",
            actor=access,
        )

    session_row = db.scalar(select(UserSession).where(UserSession.user_id == user.id))
    expires_at = session_row.expires_at.isoformat() if session_row else ""
    db.commit()
    return LoginResponse(
        session_token=raw,
        expires_at=expires_at,
        user=UserRead.model_validate(user),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    x_brain_session: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """End the caller's own session.

    Idempotent and uninformative: revoking an unknown or already-revoked
    session answers 204, so the route is not a probe for valid secrets.
    """
    revoke_session(db, x_brain_session)
    db.commit()
    return None


@router.post("/bootstrap", response_model=MeResponse)
def bootstrap_first_owner(
    x_brain_session: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """Claim first-owner of the default workspace — explicitly, and only once.

    The chicken-and-egg of a new Brain: nobody can be invited before someone owns
    it. This is the one bounded exception — the signed-in caller becomes owner
    ONLY if the workspace still has zero members. It is a deliberate call (never
    a login side-effect, never model output), and it fails closed the instant any
    membership exists, so it can never seize a workspace that already has a home.
    """
    from .identity import add_member, membership_access
    from .models import DEFAULT_WORKSPACE_ID, Workspace, WorkspaceMember
    from .services import audit
    from .sessions import resolve_session

    row = resolve_session(db, x_brain_session)
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign-in required")
    user = db.get(User, row.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign-in required")
    workspace = db.get(Workspace, DEFAULT_WORKSPACE_ID)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No workspace to claim")
    already = db.scalar(
        select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace.id).limit(1)
    )
    if already is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This Brain already has a member. Ask an owner to invite you.",
        )
    add_member(db, workspace, user, role="owner")
    access = membership_access(db, user, workspace)
    audit(
        db,
        workspace.id,
        "auth.bootstrap",
        "user",
        user.id,
        f"Claimed first-owner as {user.email or user.display_name or user.id}",
        actor=access,
    )
    db.commit()
    return MeResponse(
        user=UserRead.model_validate(user),
        memberships=[
            MembershipRead(
                workspace_id=workspace.id,
                workspace_slug=workspace.slug,
                workspace_name=workspace.name,
                role="owner",
            )
        ],
    )


@router.get("/me", response_model=MeResponse)
def me(
    x_brain_session: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """Who is asking, and what they are a member of.

    Deliberately separate from `resolve_access`: this reports identity and
    membership rather than resolving one workspace, so a person in no workspace
    yet can still see who they are signed in as.
    """
    from .sessions import resolve_session

    row = resolve_session(db, x_brain_session)
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign-in required")
    user = db.get(User, row.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign-in required")
    rows = list(
        db.execute(
            select(WorkspaceMember, Workspace)
            .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
            .where(WorkspaceMember.user_id == user.id)
        ).all()
    )
    return MeResponse(
        user=UserRead.model_validate(user),
        memberships=[
            MembershipRead(
                workspace_id=workspace.id,
                workspace_slug=workspace.slug,
                workspace_name=workspace.name,
                role=member.role,
            )
            for member, workspace in rows
        ],
    )
