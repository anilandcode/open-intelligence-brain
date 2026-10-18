"""Staged action ledger: Open Brain's approval queue for brokered writes.

Mutating tool calls (LINKEDIN_CREATE_POST, X_CREATE_POST, X_DELETE_POST,
OPENBRAIN_PROXY_EXECUTE writes) never fire directly from an agent session.
They land here as PENDING rows; only the approve endpoint executes them, and
exactly once: the PENDING -> EXECUTING transition is an atomic conditional
update, so a double-clicked Approve turns into a 409, never a duplicate post.
The provider's returned post URN is recorded on the row.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class StagedAction(Base):
    __tablename__ = "staged_actions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    account_alias: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    result_urn: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="system")
    created_by_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_by_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    decided_by_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
