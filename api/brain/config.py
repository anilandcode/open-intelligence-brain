from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./data/brain.db"
    owner_token: str = "local-dev-token"
    seed_demo: bool = True
    cors_origins: str = (
        "http://localhost:5173,http://localhost:5186,http://127.0.0.1:5173,http://127.0.0.1:5186"
    )
    cors_origin_regex: str = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"

    # Memory engine. Hosted by default because the engine is what turns capture
    # into a proposal worth reviewing; unset falls back to local extraction
    # rather than failing, so a fresh clone still runs.
    supermemory_base_url: str = "https://api.supermemory.ai"
    supermemory_api_key: str = ""
    supermemory_timeout: float = 10.0

    # Strict local mode refuses a hosted engine before any network call, and is
    # checked in `get_engine` rather than inside the client so a caller that
    # forgets cannot dial out anyway.
    strict_local: bool = False

    # Jev shadow decision provider. Configuration lives here — never in a
    # request parameter — so no API caller can point the server at an
    # arbitrary URL (SSRF). Empty means the deterministic provider only.
    jev_url: str = ""

    # Human identity. Optional by construction: with the provider name empty no
    # identity provider is configured, the machine-token path is unchanged, and
    # no route requires a person to sign in (invariant 10).
    #
    # `identity_provider` names the verifier at the boundary (`identity.py`).
    # "local" reads `identity_dev_claims`, a JSON object mapping a dev credential
    # to its claims — for local development only, never for a deployment.
    # "firebase" verifies a Firebase ID token against `identity_firebase_project_id`.
    # Nothing anywhere may trust a request body, a query parameter, or model
    # output to say who a caller is.
    identity_provider: str = ""
    identity_dev_claims: str = ""
    identity_firebase_project_id: str = ""

    # Public origin of this deployment (no trailing slash). Used as the OAuth
    # issuer and to advertise the hosted MCP URL `{public_base_url}/mcp`.
    # Local default matches uvicorn; set BRAIN_PUBLIC_BASE_URL on Cloud Run to
    # the service URL so Cursor/Claude can complete OAuth redirects.
    public_base_url: str = "http://127.0.0.1:8000"

    # When false, Streamable HTTP MCP + OAuth routes are not mounted. Stdio MCP
    # and the legacy /api/v1/mcp adapter stay available either way.
    mcp_hosted: bool = True

    # Embeddings for hybrid (vector + keyword) retrieval. When `embedding_base_url`
    # is set, neural embeddings give real semantic search; otherwise a built-in
    # lexical (hashing) embedder keeps the vector channel live at zero cost. The
    # vector path fuses with full-text via reciprocal-rank fusion either way.
    embedding_base_url: str = ""  # e.g. https://api.openai.com — any /v1/embeddings
    embedding_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"

    model_config = SettingsConfigDict(env_file=".env", env_prefix="BRAIN_", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
