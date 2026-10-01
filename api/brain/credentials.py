"""Hashed machine API credentials.

A machine credential is not a person and is not a session. It is a high-entropy
secret minted once, returned once, and stored only as a SHA-256 digest. Lookup
is by hash; revocation is immediate; scopes are enforced centrally.

Legacy `workspace_grants.principal` values (including the bootstrap owner token)
remain valid during the v1.1 transition so a prior revision can still operate
against the expanded schema. New tokens go through this module.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ApiCredential, ApiCredentialScope, Workspace, new_id, now_utc

# Displayable product scopes. Unknown values are refused at mint time so a typo
# cannot silently mint an unrestricted credential.
KNOWN_SCOPES: frozenset[str] = frozenset(
    {
        "brain:read",
        "brain:ask",
        "sources:read",
        "sources:write",
        "reviews:read",
        "reviews:write",
        "memory:read",
        "memory:write",
        "imports:create",
        "graph:read",
        "skills:read",
        "skills:execute",
        "connectors:read",
        "connectors:manage",
        "turns:read",
        "turns:execute",
        "admin",
    }
)

_KEY_PREFIX = "brn_live"


def hash_api_key(raw: str) -> str:
    """One-way digest of a machine secret. The only form we ever persist."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _new_raw_key(key_id: str) -> str:
    # key_id is embedded so a leaked listing preview never reconstructs the secret,
    # and so operators can recognise which row a pasting agent was given.
    return f"{_KEY_PREFIX}_{key_id}_{secrets.token_hex(24)}"


def _key_prefix_from_raw(raw: str) -> str:
    """Non-recoverable head used in listings and audit previews."""
    # brn_live_<id>_… → keep scheme + id, drop the secret tail.
    parts = raw.split("_")
    if len(parts) >= 3 and parts[0] == "brn" and parts[1] == "live":
        return f"brn_live_{parts[2]}"
    return raw[:12]


def validate_scopes(scopes: list[str] | None) -> list[str] | None:
    """Normalise and refuse unknown scopes. None means unrestricted."""
    if scopes is None:
        return None
    cleaned = sorted({s.strip() for s in scopes if s and s.strip()})
    if not cleaned:
        return None
    unknown = [s for s in cleaned if s not in KNOWN_SCOPES]
    if unknown:
        raise ValueError(f"Unknown scope(s): {', '.join(unknown)}")
    return cleaned


def create_api_credential(
    db: Session,
    workspace: Workspace,
    *,
    name: str = "",
    role: str = "member",
    scopes: list[str] | None = None,
    expires_at: datetime | None = None,
    owner_user_id: str | None = None,
) -> tuple[str, ApiCredential]:
    """Mint a credential. Returns (raw_secret, row). Raw is never written."""
    normalised = validate_scopes(scopes)
    cred_id = new_id("key")
    raw = _new_raw_key(cred_id.replace("key_", ""))
    cred = ApiCredential(
        id=cred_id,
        workspace_id=workspace.id,
        owner_user_id=owner_user_id,
        name=(name or "")[:120],
        key_prefix=_key_prefix_from_raw(raw),
        key_hash=hash_api_key(raw),
        role=role,
        expires_at=expires_at,
        created_at=now_utc(),
    )
    db.add(cred)
    db.flush()
    if normalised is not None:
        for scope in normalised:
            db.add(ApiCredentialScope(credential_id=cred.id, scope=scope))
        db.flush()
    return raw, cred


def _is_expired(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return False
    expiry = expires_at.replace(tzinfo=None) if expires_at.tzinfo is None else expires_at
    now = datetime.now(UTC).replace(tzinfo=None) if expiry.tzinfo is None else datetime.now(UTC)
    return expiry < now


def resolve_api_credential(db: Session, raw: str) -> ApiCredential | None:
    """Look a live credential up by its secret, or None if unknown/revoked/expired."""
    if not raw or not raw.startswith(f"{_KEY_PREFIX}_"):
        return None
    cred = db.scalar(select(ApiCredential).where(ApiCredential.key_hash == hash_api_key(raw)))
    if cred is None:
        return None
    if cred.revoked_at is not None:
        return None
    if _is_expired(cred.expires_at):
        return None
    return cred


def credential_scopes(db: Session, credential_id: str) -> frozenset[str] | None:
    """The scopes attached to a credential. None means unrestricted (no rows)."""
    rows = list(
        db.scalars(
            select(ApiCredentialScope.scope).where(
                ApiCredentialScope.credential_id == credential_id
            )
        ).all()
    )
    if not rows:
        return None
    return frozenset(rows)


def touch_last_used(db: Session, cred: ApiCredential) -> None:
    cred.last_used_at = datetime.now(UTC)
    db.flush()


def revoke_api_credential(db: Session, credential_id: str, workspace_id: str) -> bool:
    """Soft-revoke. True when a live credential was marked revoked."""
    cred = db.get(ApiCredential, credential_id)
    if cred is None or cred.workspace_id != workspace_id:
        return False
    if cred.revoked_at is not None:
        return False
    cred.revoked_at = datetime.now(UTC)
    db.flush()
    return True


def list_api_credentials(db: Session, workspace_id: str) -> list[ApiCredential]:
    return list(
        db.scalars(
            select(ApiCredential)
            .where(ApiCredential.workspace_id == workspace_id)
            .order_by(ApiCredential.created_at.desc())
        ).all()
    )


def scopes_for_credential(db: Session, cred: ApiCredential) -> list[str]:
    rows = credential_scopes(db, cred.id)
    return sorted(rows) if rows is not None else []
