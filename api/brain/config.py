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
    # Google Identity Services OAuth client id — the audience a Google ID token
    # from the browser sign-in button is verified against (identity.py "google").
    identity_google_client_id: str = ""

    # mcp-auth-bridge control plane (the OAuth/tool broker). Empty keeps the
    # connections surfaces offline (they answer 503 instead of reaching out).
    mab_bridge_url: str = ""
    mab_service_token: str = ""

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

    # Intake: at most this many locally extracted proposals per source version,
    # best-scoring spans first. Every span is still stored as evidence; the cap
    # only keeps the review queue reviewable. 0 disables the cap.
    max_proposals_per_version: int = 12

    # With embeddings configured, an approved item this close to the question
    # (cosine, 0..1) counts as answering it even when the wording differs.
    answer_min_similarity: float = 0.55

    # Optional chat model (any OpenAI-compatible `/chat/completions`) used to
    # extract self-contained claims at capture. Unset keeps the deterministic
    # extractor. On the VM this can be the LLM proxy: http://127.0.0.1:6799/v1
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout: float = 45.0
    # Model extraction reads the source in windows of this many characters,
    # at most `llm_max_windows` per version, and proposes at most
    # `llm_max_claims_per_version` claims.
    llm_window_chars: int = 4000
    llm_max_windows: int = 8
    llm_max_claims_per_version: int = 25
    # With a model configured, `/api/v1/chat` and `ask_brain` answer in the
    # model's words, every sentence cited and checked against its items.
    # False keeps answers as quotes of the approved statements.
    llm_write_answers: bool = True

    # Keeping knowledge current. A time-sensitive claim (price, owner, plan)
    # gets a review-by date this many days after approval. The gardening
    # report calls an item unused when nothing cited it for `unused_after_days`.
    default_review_days: int = 90
    unused_after_days: int = 120
    # The weekly gardening digest is not re-sent within this many days.
    gardening_min_days: int = 6
    # A folder sync fetches at most this many changed documents per run, so
    # one large folder cannot hold the request (the next run picks up the rest).
    watch_max_documents: int = 50

    model_config = SettingsConfigDict(env_file=".env", env_prefix="BRAIN_", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
