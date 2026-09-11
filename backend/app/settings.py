"""Application settings.

Every value has a working default so the API boots with an empty environment.
In particular there is no AI or TTS credential: the deterministic core must run
without one (SDD sections 2.4 and 16).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="", extra="ignore", frozen=True, populate_by_name=True
    )

    app_env: str = Field(default="local", alias="APP_ENV")
    app_name: str = Field(default="Adaptive Meditation API", alias="APP_NAME")
    api_version: str = Field(default="0.1.0", alias="API_VERSION")

    # Secrets arrive from the runtime environment, never from Git.
    database_url: str = Field(
        default="postgresql+psycopg://adaptive:adaptive@localhost:5432/adaptive",
        alias="DATABASE_URL",
    )
    database_pool_size: int = Field(default=5, alias="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(default=5, alias="DATABASE_MAX_OVERFLOW")

    knowledge_dir: Path = Field(default=REPO_ROOT / "knowledge", alias="KNOWLEDGE_DIR")

    # "null" is the only provider implemented in Program001. A future provider
    # personalizes wording only; it never owns the practice decision.
    ai_provider: str = Field(default="null", alias="AI_PROVIDER")
    tts_provider: str = Field(default="null", alias="TTS_PROVIDER")
    ai_api_key: str | None = Field(default=None, alias="AI_API_KEY")

    @property
    def ai_enabled(self) -> bool:
        return self.ai_provider != "null" and bool(self.ai_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
