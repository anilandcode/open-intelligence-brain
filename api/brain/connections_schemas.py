"""Request/response models for the connections and staged-action surfaces."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ConnectionRead(BaseModel):
    connected_account_id: str
    toolkit_slug: str
    alias: str
    provider_account_id: str = ""
    display_name: str = ""
    status: str
    expires_at: datetime | None = None
    # Never a token: the bridge masks credentials and Open Brain does not ask.
    credential_state: str = "unknown"


class LinkStartRead(BaseModel):
    authorization_url: str
    session_uri: str


class AliasUpdate(BaseModel):
    alias: str = Field(min_length=1, max_length=63, pattern=r"^[a-z0-9][a-z0-9_-]{0,62}$")


class LinkStartRequest(BaseModel):
    toolkit_slug: str = Field(default="x", max_length=32)
    alias: str = Field(
        default="personal-x", min_length=1, max_length=63, pattern=r"^[a-z0-9][a-z0-9_-]{0,62}$"
    )


class VerifyRequest(BaseModel):
    session_uri: str = Field(min_length=1)


class VerifyRead(BaseModel):
    connected_account_id: str
    status: str


class StagedActionCreate(BaseModel):
    tool_name: str = Field(min_length=1, max_length=64)
    account_alias: str = Field(min_length=1, max_length=63)
    payload: dict = Field(default_factory=dict)


class StagedActionRead(BaseModel):
    id: str
    tool_name: str
    account_alias: str
    payload: dict = Field(default_factory=dict)
    status: str
    result_urn: str = ""
    error: str = ""
    created_at: datetime
    decided_at: datetime | None = None
