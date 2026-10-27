"""Refuse unsafe defaults on a public deployment.

Every default in `config.py` is chosen so a fresh clone runs with no setup: a
known owner token, seeded demo data, an open first-owner claim. Those are the
right defaults on loopback and the wrong ones on the internet, and nothing used
to notice the difference. A deployment advertising an HTTPS public origin
(`BRAIN_PUBLIC_BASE_URL`) is treated as public, and boot refuses to grant owner
to a token anyone can read in this repository.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import token_preview
from .config import Settings
from .models import WorkspaceGrant

logger = logging.getLogger(__name__)

DEFAULT_OWNER_TOKEN = "local-dev-token"
MIN_PUBLIC_TOKEN_LENGTH = 32


class UnsafeDeployment(RuntimeError):
    """Boot refused: a public deployment is running on a published default."""


def check_owner_token(settings: Settings) -> None:
    if not settings.is_public_deployment:
        return
    token = settings.owner_token
    if not token or token == DEFAULT_OWNER_TOKEN:
        raise UnsafeDeployment(
            "BRAIN_OWNER_TOKEN is unset or the published default on a public deployment "
            f"({settings.public_base_url}). Set a long random value before starting."
        )
    if len(token) < MIN_PUBLIC_TOKEN_LENGTH:
        logger.warning(
            "BRAIN_OWNER_TOKEN is shorter than %d characters on a public deployment; "
            "it is a long-lived owner credential and should be long and random.",
            MIN_PUBLIC_TOKEN_LENGTH,
        )


def should_seed_demo(settings: Settings) -> bool:
    """Demo data never lands in a public Brain, whatever BRAIN_SEED_DEMO says."""
    if settings.seed_demo and settings.is_public_deployment:
        logger.warning("BRAIN_SEED_DEMO ignored: demo data is never seeded on a public deployment")
        return False
    return settings.seed_demo


def stale_owner_grants(db: Session, owner_token: str) -> list[WorkspaceGrant]:
    """Legacy owner grants left behind by an owner-token rotation.

    Machine keys minted through the API live in `api_credentials`; the only
    owner rows `workspace_grants` should hold are for the configured bootstrap
    token. Anything else with the owner role is a previous token.
    """
    rows = db.scalars(
        select(WorkspaceGrant).where(
            WorkspaceGrant.role == "owner", WorkspaceGrant.principal != owner_token
        )
    ).all()
    return [row for row in rows if not row.principal.startswith("brn_")]


def report_or_retire_stale_owner_grants(db: Session, settings: Settings) -> int:
    stale = stale_owner_grants(db, settings.owner_token)
    if not stale:
        return 0
    previews = ", ".join(sorted({token_preview(row.principal) for row in stale}))
    if not settings.retire_legacy_owner_grants:
        logger.warning(
            "%d legacy owner grant(s) belong to a token other than BRAIN_OWNER_TOKEN (%s). "
            "They still have owner access. Set BRAIN_RETIRE_LEGACY_OWNER_GRANTS=true to "
            "remove them at next boot.",
            len(stale),
            previews,
        )
        return 0
    for row in stale:
        db.delete(row)
    logger.warning("Retired %d legacy owner grant(s): %s", len(stale), previews)
    return len(stale)
