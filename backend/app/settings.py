"""Application settings.

Every value has a working default so the API boots with an empty environment.
In particular there is no AI or TTS credential: the deterministic core must run
without one (SDD sections 2.4 and 16).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.legal.operator import OperatorIdentity, operator_from_settings
from app.persistence.schema_isolation import TEST_SCHEMA_PREFIX, is_test_schema

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="", extra="ignore", frozen=True, populate_by_name=True
    )

    # development | staging | production. Configuration only: no business logic
    # branches on this, because a flavour that changes behaviour is a second
    # product to test.
    app_env: str = Field(default="development", alias="APP_ENV")
    app_name: str = Field(default="Adaptive Meditation API", alias="APP_NAME")
    api_version: str = Field(default="0.1.0", alias="API_VERSION")

    # Secrets arrive from the runtime environment, never from Git.
    database_url: str = Field(
        default="postgresql+psycopg://adaptive:adaptive@localhost:5432/adaptive",
        alias="DATABASE_URL",
    )
    # PostgreSQL schema to place the application's tables in. Empty means the
    # connection's default search_path. The test suite sets a unique one per run.
    database_schema: str = Field(default="", alias="DATABASE_SCHEMA")
    database_pool_size: int = Field(default=5, alias="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(default=5, alias="DATABASE_MAX_OVERFLOW")

    knowledge_dir: Path = Field(default=REPO_ROOT / "knowledge", alias="KNOWLEDGE_DIR")

    # Legal operator identity. Individual today, possibly a company later; the
    # legal surfaces read these rather than hard-coding a name.
    operator_brand_name: str = Field(default="", alias="OPERATOR_BRAND_NAME")
    operator_legal_form: str = Field(default="individual", alias="OPERATOR_LEGAL_FORM")
    operator_contact_email: str = Field(default="", alias="OPERATOR_CONTACT_EMAIL")
    operator_support_url: str = Field(default="", alias="OPERATOR_SUPPORT_URL")
    operator_jurisdiction: str = Field(default="", alias="OPERATOR_JURISDICTION")

    # "null" is the only provider implemented in Program001. A future provider
    # personalizes wording only; it never owns the practice decision.
    ai_provider: str = Field(default="null", alias="AI_PROVIDER")
    tts_provider: str = Field(default="null", alias="TTS_PROVIDER")
    ai_api_key: str | None = Field(default=None, alias="AI_API_KEY")

    @model_validator(mode="after")
    def _refuse_test_schema_in_production(self) -> Settings:
        """A production process must never be pointed at a test schema.

        The test suite creates and drops schemas named ``test_*``. If production
        configuration could select one, a deploy would either read an empty
        database or have its tables dropped by a passing test run. The guard is
        here rather than in the test helper because it has to hold for
        configuration the tests never see.
        """
        if self.app_env != "production":
            return self
        if is_test_schema(self.database_schema):
            raise ValueError(
                f"DATABASE_SCHEMA={self.database_schema!r} is a test schema and "
                "cannot be used in production"
            )
        if "search_path" in self.database_url and TEST_SCHEMA_PREFIX in self.database_url:
            raise ValueError(
                "DATABASE_URL sets a search_path naming a test schema; refusing "
                "to start in production"
            )
        return self

    @property
    def ai_enabled(self) -> bool:
        return self.ai_provider != "null" and bool(self.ai_api_key)

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def operator(self) -> OperatorIdentity:
        return operator_from_settings(
            brand_name=self.operator_brand_name,
            legal_form=self.operator_legal_form,
            contact_email=self.operator_contact_email,
            support_url=self.operator_support_url,
            jurisdiction=self.operator_jurisdiction,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
