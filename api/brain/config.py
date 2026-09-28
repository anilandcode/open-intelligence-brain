from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./data/brain.db"
    owner_token: str = "local-dev-token"
    seed_demo: bool = True
    cors_origins: str = "http://localhost:5173,http://localhost:5186,http://127.0.0.1:5173,http://127.0.0.1:5186"
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

    model_config = SettingsConfigDict(env_file=".env", env_prefix="BRAIN_", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
