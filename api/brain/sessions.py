"""Human sessions: turning a verified identity into a usable credential.

This is the auth layer the identity boundary deliberately left out. It does one
thing — exchange a provider credential for a short-lived session — and refuses
to do the other thing, which is decide what that session may reach. Reach comes
from `workspace_members`, resolved on every request.

Three rules the design rests on:

1. **The session secret is never stored.** `create_session` returns the raw
   value exactly once and keeps only its SHA-256 hash. An export, a backup, or
   a leaked dump yields nothing usable.
2. **A session is not a machine token and a machine token is not a session.**
   They travel in different headers (`X-Brain-Session` vs `X-Brain-Token`) and
   resolve through different tables. Neither is accepted where the other is
   expected, so an audit row can always say which class acted.
3. **Revocation is immediate and needs no session walk.** A deactivated user or
   a dropped membership stops working at the next request because reach is
   resolved per request, not captured in the session.

Sessions are optional (invariant 10): with no identity provider configured the
login route refuses and every machine-token caller is unaffected.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .access import AccessDenied, Workspace, WorkspaceAccess
from .identity import IdentityError, get_identity_provider, membership_access, upsert_user
from .models import User, UserSession, new_id

# Opaque and 256-bit. No structure, no user id, no signature: there is nothing
# in the value to tamper with, and nothing to learn from it if it leaks.
_SESSION_PREFIX = "bss"
SESSION_HOURS = 12


def hash_session_token(raw: str) -> str:
    """One-way digest of a session secret. The only form we ever persist."""
    import hashlib

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _new_session_token() -> str:
    import secrets

    return f"{_SESSION_PREFIX}_{secrets.token_hex(32)}"


def create_session(db: Session, user: User, user_agent: str = "") -> tuple[str, UserSession]:
    """Mint a session and return (raw_secret, row).

    The raw secret is returned to the caller and never written to the database
    or a log. Callers must not persist it anywhere except the client.
    """
    raw = _new_session_token()
    session_row = UserSession(
        id=new_id("ses"),
        user_id=user.id,
        token_hash=hash_session_token(raw),
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=SESSION_HOURS),
        user_agent=(user_agent or "")[:240],
    )
    db.add(session_row)
    db.flush()
    return raw, session_row


def _is_expired(expires_at) -> bool:
    """Compare an expiry against now across both dialects.

    SQLite hands back naive datetimes and PostgreSQL hands back aware ones, and
    Python raises TypeError when the two meet. Detect from the VALUE's own
    tzinfo rather than from the engine name.
    """
    expiry = expires_at.replace(tzinfo=None) if expires_at.tzinfo is None else expires_at
    now = datetime.now(UTC).replace(tzinfo=None) if expiry.tzinfo is None else datetime.now(UTC)
    return expiry < now


def resolve_session(db: Session, raw_token: str) -> UserSession | None:
    """Look a session up by its secret, or None if it is unknown, expired, or
    belongs to a person who can no longer sign in.

    Returning None rather than raising keeps one caller-side rule: an
    unauthenticated request is 401 with the same message whether the session
    never existed, has expired, or was revoked.
    """
    if not raw_token:
        return None
    row = db.scalar(
        select(UserSession).where(UserSession.token_hash == hash_session_token(raw_token))
    )
    if row is None:
        return None
    if _is_expired(row.expires_at):
        return None
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        return None
    return row


def resolve_session_access(
    db: Session, raw_token: str, requested_slug: str | None = None
) -> WorkspaceAccess:
    """A session plus an optional workspace slug into a scoped access object.

    Mirrors `resolve_workspace` exactly on purpose: one grant means the
    workspace is implied, several mean the caller must name one, and a person
    with no membership anywhere is refused rather than dropped into a default.
    """
    row = resolve_session(db, raw_token)
    if row is None:
        raise AccessDenied("Sign-in required")
    user = db.get(User, row.user_id)
    if user is None:
        raise AccessDenied("Sign-in required")

    from .models import WorkspaceMember

    members = list(
        db.scalars(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)).all()
    )
    if not members:
        # Signed in, but not a member of anything. That is not a transient
        # error and must not read like a bad credential — the person needs an
        # invitation, not a password reset.
        raise AccessDenied("This account has no workspace yet")

    if requested_slug:
        workspace = db.scalar(select(Workspace).where(Workspace.slug == requested_slug))
        if workspace is None:
            raise AccessDenied("Unknown workspace")
        access = membership_access(db, user, workspace)
        if access is None:
            # No live membership here: same answer as a workspace that does not
            # exist, so membership cannot be probed.
            raise AccessDenied("Unknown workspace")
        return access

    if len(members) > 1:
        raise AccessDenied(
            "This account reaches several workspaces; send the X-Brain-Workspace header"
        )

    workspace = db.get(Workspace, members[0].workspace_id)
    if workspace is None:
        raise AccessDenied("Unknown workspace")
    access = membership_access(db, user, workspace)
    if access is None:
        raise AccessDenied("Sign-in required")
    return access


def sign_in_with_credential(db: Session, credential: str, user_agent: str = "") -> tuple[str, User]:
    """Verify a provider credential and mint a session for the person behind it.

    The provider boundary runs FIRST: a credential that does not verify creates
    no user row and no session. What comes back is the only raw secret the
    caller will ever see for this sign-in.
    """
    provider = get_identity_provider()
    if provider is None:
        raise IdentityError("Sign-in failed")
    verified = provider.verify(credential)
    user = upsert_user(db, verified)
    raw, _row = create_session(db, user, user_agent=user_agent)
    return raw, user


def revoke_session(db: Session, raw_token: str) -> bool:
    """End one session. True when something was actually revoked."""
    if not raw_token:
        return False
    token_hash = hash_session_token(raw_token)
    row = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash))
    if row is None:
        return False
    db.execute(delete(UserSession).where(UserSession.id == row.id))
    db.flush()
    return True


def revoke_all_sessions(db: Session, user_id: str) -> int:
    """End every session a person holds. Returns how many were removed.

    Used when a person is deactivated: reach stops immediately either way
    (membership is resolved per request), but ending the sessions too means the
    credentials themselves are gone rather than merely ignored.
    """
    result = db.execute(delete(UserSession).where(UserSession.user_id == user_id))
    db.flush()
    return int(result.rowcount or 0)
