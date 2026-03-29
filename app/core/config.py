from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="Teacher Helper", validation_alias=AliasChoices("app_name", "APP_NAME"))
    database_url: str = Field(default="sqlite:///./teacher_helper.db", validation_alias=AliasChoices("database_url", "DATABASE_URL"))
    llm_provider: Literal["deterministic", "openai"] = Field(default="deterministic", validation_alias=AliasChoices("llm_provider", "LLM_PROVIDER"))
    openai_api_key: str | None = Field(default=None, validation_alias=AliasChoices("openai_api_key", "OPENAI_API_KEY"))
    openai_base_url: str | None = Field(default=None, validation_alias=AliasChoices("openai_base_url", "OPENAI_BASE_URL"))
    openai_model: str = Field(default="gpt-4o-mini", validation_alias=AliasChoices("openai_model", "OPENAI_MODEL"))
    duplicate_lesson_policy: Literal["reject", "overwrite"] = Field(default="reject", validation_alias=AliasChoices("duplicate_lesson_policy", "DUPLICATE_LESSON_POLICY"))
    session_timeout_minutes: int = Field(default=30, validation_alias=AliasChoices("session_timeout_minutes", "SESSION_TIMEOUT_MINUTES"))
    supported_languages: str = Field(default="English", validation_alias=AliasChoices("supported_languages", "SUPPORTED_LANGUAGES"))
    log_level: str = Field(default="INFO", validation_alias=AliasChoices("log_level", "LOG_LEVEL"))
    allow_origins: str = Field(default="http://localhost:5173", validation_alias=AliasChoices("allow_origins", "ALLOW_ORIGINS"))
    ncert_chunk_size: int = Field(default=650, validation_alias=AliasChoices("ncert_chunk_size", "NCERT_CHUNK_SIZE"))
    ncert_top_k: int = Field(default=3, validation_alias=AliasChoices("ncert_top_k", "NCERT_TOP_K"))
    reset_db_on_start: bool = Field(default=False, validation_alias=AliasChoices("reset_db_on_start", "RESET_DB_ON_START"))

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value:
            raise ValueError("DATABASE_URL cannot be empty.")
        return value

    @field_validator("session_timeout_minutes")
    @classmethod
    def validate_timeout(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("SESSION_TIMEOUT_MINUTES must be greater than 0.")
        return value

    @property
    def database_is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def supported_languages_list(self) -> list[str]:
        return [item.strip() for item in self.supported_languages.split(",") if item.strip()]

    @property
    def supported_languages_casefold(self) -> set[str]:
        return {item.casefold() for item in self.supported_languages_list}

    @property
    def allow_origins_list(self) -> list[str]:
        return [item.strip() for item in self.allow_origins.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
