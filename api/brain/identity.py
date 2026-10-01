"""Identity provider boundary: who a human is, and how we come to believe it.

Identity is an ASSERTION FROM AN IDENTITY PROVIDER. It is verified at this
boundary and only then becomes a row in `users`. Nothing in a request body, a
query parameter, a captured event, or model output can name a user: a caller
presents a credential, a provider verifies it, and the verified result is the
only thing that may be upserted.

Two credential classes exist side by side and are never interchangeable:

- machine: `workspace_grants.principal` — an opaque token (see `access.py`).
  It carries a role and reaches a workspace, but it is not a person.
- human:   `users` + `workspace_members` — reached only through a verified
  provider assertion. A `User` row is not a credential and cannot be sent in
  a header.

A provider that fails to verify must leave no trace in `users`: the verify step
happens before any write, so a bad credential cannot even create an account.

This module is optional by construction (invariant 10). With no provider
configured, `get_identity_provider()` returns None and the whole machine-token
surface behaves exactly as it did before identity existed.

Deliberately out of scope here: login sessions and HTTP routes. Those belong to
the auth layer, which calls into this module rather than re-implementing
verification.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from pydantic_settings import SettingsConfigDict  # noqa: F401  (documents Settings parity)
from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import WorkspaceAccess
from .config import Settings, get_settings
from .models import User, Workspace, WorkspaceMember, new_id, now_utc


class IdentityError(Exception):
    """The credential did not verify.

    Deliberately uninformative: an error that says "unknown subject" versus
    "wrong signature" is a user enumeration oracle.
    """


@dataclass(frozen=True)
class VerifiedIdentity:
    """A provider's assertion about a human, already verified.

    Carries the external identity (`provider`, `subject`) plus display metadata.
    Only the first two are a key; the rest are advisory and must never decide
    access.
    """

    provider: str
    subject: str
    email: str = ""
    display_name: str = ""


@runtime_checkable
class IdentityProvider(Protocol):
    """A verifier at the trust boundary.

    One method, one rule: raise `IdentityError` rather than return a partially
    trusted identity. A caller that catches the exception gets nothing.
    """

    name: str

    def verify(self, credential: str) -> VerifiedIdentity: ...


class LocalIdentityProvider:
    """Pre-provisioned dev identities. Never for a deployment.

    The credential is a development string mapped to its claims in
    `identity_dev_claims`. There is no password check here and none should be
    added: hand-rolling password verification is the auth layer's job, and a
    half-real check is worse than an honest one that says "bring your own
    provider".
    """

    name = "local"

    def __init__(self, claims: dict[str, dict]) -> None:
        self._claims = claims

    def verify(self, credential: str) -> VerifiedIdentity:
        claims = self._claims.get(credential) if credential else None
        if not isinstance(claims, dict):
            raise IdentityError("Sign-in failed")
        subject = claims.get("subject")
        if not subject or not isinstance(subject, str):
            raise IdentityError("Sign-in failed")
        return VerifiedIdentity(
            provider=self.name,
            subject=subject,
            email=str(claims.get("email") or ""),
            display_name=str(claims.get("display_name") or ""),
        )


class FirebaseIdentityProvider:
    """Verify a Firebase ID token. Hosted browser path for Google sign-in.

    The credential is a Firebase ID token from the client SDK. Verification
    uses Google's certs (via `google-auth`); a failed or expired token raises
    `IdentityError` with the same uninformative message as every other failure.
    The stable subject is the Firebase UID — never the email.
    """

    name = "firebase"

    def __init__(self, project_id: str) -> None:
        if not project_id or not project_id.strip():
            raise ValueError("identity_provider=firebase requires identity_firebase_project_id")
        self.project_id = project_id.strip()

    def verify(self, credential: str) -> VerifiedIdentity:
        if not credential or not credential.strip():
            raise IdentityError("Sign-in failed")
        try:
            from google.auth.transport import requests as google_requests
            from google.oauth2 import id_token
        except ImportError as exc:
            raise IdentityError("Sign-in failed") from exc
        try:
            claims = id_token.verify_firebase_token(
                credential.strip(),
                google_requests.Request(),
                audience=self.project_id,
            )
        except Exception as exc:
            # Any failure mode (bad sig, wrong audience, expired) → one message.
            raise IdentityError("Sign-in failed") from exc
        if not isinstance(claims, dict):
            raise IdentityError("Sign-in failed")
        subject = claims.get("sub") or claims.get("user_id")
        if not subject or not isinstance(subject, str):
            raise IdentityError("Sign-in failed")
        name = claims.get("name") or ""
        email = claims.get("email") or ""
        return VerifiedIdentity(
            provider=self.name,
            subject=subject,
            email=str(email),
            display_name=str(name),
        )


def get_identity_provider(settings: Settings | None = None) -> IdentityProvider | None:
    """The configured provider, or None when identity is not in use.

    None is a first-class answer: it means the deployment runs on machine
    credentials alone and every identity-aware route must refuse a human login
    rather than invent one.

    A malformed provider name or malformed claims raise rather than silently
    returning None. Disabling login by typo is fail-closed for humans, but it is
    an operator error that must be visible, not a quiet default.
    """
    settings = settings or get_settings()
    name = (settings.identity_provider or "").strip().lower()
    if not name:
        return None
    if name == "local":
        import json

        raw = (settings.identity_dev_claims or "").strip()
        if not raw:
            raise ValueError("identity_provider=local requires identity_dev_claims")
        try:
            claims = json.loads(raw)
        except ValueError as exc:
            raise ValueError("identity_dev_claims must be a JSON object") from exc
        if not isinstance(claims, dict):
            raise ValueError("identity_dev_claims must be a JSON object")
        return LocalIdentityProvider(claims)
    if name == "firebase":
        return FirebaseIdentityProvider(settings.identity_firebase_project_id)
    raise ValueError(f"Unknown identity provider: {settings.identity_provider!r}")


def find_user(db: Session, provider: str, subject: str) -> User | None:
    return db.scalar(
        select(User).where(User.provider == provider, User.provider_subject == subject)
    )


def upsert_user(db: Session, identity: VerifiedIdentity) -> User:
    """Record a verified human, or update what the provider now asserts.

    The external identity is the key and is never rewritten. Email and display
    name follow the provider's latest assertion but only when it actually says
    something — a provider that omits them must not erase what we knew.
    """
    user = find_user(db, identity.provider, identity.subject)
    if user is None:
        user = User(
            id=new_id("usr"),
            provider=identity.provider,
            provider_subject=identity.subject,
            email=identity.email,
            display_name=identity.display_name,
            is_active=True,
            created_at=now_utc(),
            last_login_at=now_utc(),
        )
        db.add(user)
        db.flush()
        return user
    if identity.email:
        user.email = identity.email
    if identity.display_name:
        user.display_name = identity.display_name
    user.last_login_at = datetime.now(UTC)
    db.flush()
    return user


def add_member(
    db: Session, workspace: Workspace | None, user: User, role: str = "member"
) -> WorkspaceMember:
    """Give a person access to a workspace, replacing any existing membership.

    Mirrors `grant_workspace` so a human grant and a machine grant behave the
    same way: one row per (workspace, principal), last write wins on role.
    """
    if workspace is None:
        raise ValueError("Cannot add a member to a workspace that does not exist")
    existing = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace.id,
            WorkspaceMember.user_id == user.id,
        )
    )
    if existing is not None:
        existing.role = role
        return existing
    member = WorkspaceMember(
        id=new_id("wsm"),
        workspace_id=workspace.id,
        user_id=user.id,
        role=role,
    )
    db.add(member)
    db.flush()
    return member


def membership_role(db: Session, workspace_id: str, user_id: str) -> str | None:
    """The person's role in a workspace, or None if they have no live access.

    A deactivated user reads as having no access anywhere, immediately: revoking
    a person must not require walking every workspace they ever joined.
    """
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        return None
    member = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    return member.role if member is not None else None


def membership_access(db: Session, user: User, workspace: Workspace) -> WorkspaceAccess | None:
    """Build the same access object the machine-token path builds.

    `actor_kind`/`actor_id` record which class of credential answered, so a
    later audit row can say a person acted rather than that a token did. None
    when the person has no live membership — never an access object with an
    empty role, which would read as a member with no ceiling.
    """
    role = membership_role(db, workspace.id, user.id)
    if role is None:
        return None
    return WorkspaceAccess(
        workspace=workspace,
        principal=user.id,
        role=role,
        scope=None,
        actor_kind="user",
        actor_id=user.id,
    )
