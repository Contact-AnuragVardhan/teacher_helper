from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.language import DEFAULT_LANGUAGE, normalize_language


class Settings(BaseSettings):
    app_name: str = Field(default="Teacher Helper", validation_alias=AliasChoices("app_name", "APP_NAME"))
    database_url: str = Field(default="sqlite:///./teacher_helper.db", validation_alias=AliasChoices("database_url", "DATABASE_URL"))

    llm_provider: Literal["deterministic", "openai", "google"] = Field(
        default="openai",
        validation_alias=AliasChoices("llm_provider", "LLM_PROVIDER"),
    )

    openai_api_key: str | None = Field(default=None, validation_alias=AliasChoices("openai_api_key", "OPENAI_API_KEY"))
    openai_base_url: str | None = Field(default=None, validation_alias=AliasChoices("openai_base_url", "OPENAI_BASE_URL"))
    openai_model: str = Field(default="gpt-4o-mini", validation_alias=AliasChoices("openai_model", "OPENAI_MODEL"))

    google_api_key: str | None = Field(default=None, validation_alias=AliasChoices("google_api_key", "GOOGLE_API_KEY"))

    duplicate_lesson_policy: Literal["reject", "overwrite"] = Field(
        default="reject",
        validation_alias=AliasChoices("duplicate_lesson_policy", "DUPLICATE_LESSON_POLICY"),
    )
    session_timeout_minutes: int = Field(
        default=30,
        validation_alias=AliasChoices("session_timeout_minutes", "SESSION_TIMEOUT_MINUTES"),
    )
    supported_languages: str = Field(
        default="English,Hindi,Hinglish",
        validation_alias=AliasChoices("supported_languages", "SUPPORTED_LANGUAGES"),
    )

    profile_allowed_grades: str = Field(
        default="",
        validation_alias=AliasChoices("profile_allowed_grades", "PROFILE_ALLOWED_GRADES"),
    )
    profile_allowed_subjects_by_grade: str = Field(
        default="",
        validation_alias=AliasChoices("profile_allowed_subjects_by_grade", "PROFILE_ALLOWED_SUBJECTS_BY_GRADE"),
    )

    whatsapp_access_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("whatsapp_access_token", "WHATSAPP_ACCESS_TOKEN"),
    )
    whatsapp_phone_number_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("whatsapp_phone_number_id", "WHATSAPP_PHONE_NUMBER_ID"),
    )
    whatsapp_verify_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("whatsapp_verify_token", "WHATSAPP_VERIFY_TOKEN"),
    )
    whatsapp_graph_version: str = Field(
        default="v23.0",
        validation_alias=AliasChoices("whatsapp_graph_version", "WHATSAPP_GRAPH_VERSION"),
    )
    whatsapp_api_timeout_seconds: float = Field(
        default=15.0,
        validation_alias=AliasChoices("whatsapp_api_timeout_seconds", "WHATSAPP_API_TIMEOUT_SECONDS"),
    )

    jalta_sitara_hotline_language_api_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "jalta_sitara_hotline_language_api_enabled",
            "JALTA_SITARA_HOTLINE_LANGUAGE_API_ENABLED",
            # Backward-compatible aliases for older deployments.
            "student_helper_language_api_enabled",
            "STUDENT_HELPER_LANGUAGE_API_ENABLED",
        ),
    )
    jalta_sitara_hotline_base_url: str = Field(
        default="https://student-helper-reai.onrender.com",
        validation_alias=AliasChoices(
            "jalta_sitara_hotline_base_url",
            "JALTA_SITARA_HOTLINE_BASE_URL",
            # Backward-compatible aliases for older deployments.
            "student_helper_base_url",
            "STUDENT_HELPER_BASE_URL",
        ),
    )
    jalta_sitara_hotline_language_api_timeout_seconds: float = Field(
        default=5.0,
        validation_alias=AliasChoices(
            "jalta_sitara_hotline_language_api_timeout_seconds",
            "JALTA_SITARA_HOTLINE_LANGUAGE_API_TIMEOUT_SECONDS",
            # Backward-compatible aliases for older deployments.
            "student_helper_language_api_timeout_seconds",
            "STUDENT_HELPER_LANGUAGE_API_TIMEOUT_SECONDS",
        ),
    )

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

    @field_validator("whatsapp_graph_version")
    @classmethod
    def validate_graph_version(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("WHATSAPP_GRAPH_VERSION cannot be empty.")
        return value

    @field_validator("whatsapp_api_timeout_seconds")
    @classmethod
    def validate_whatsapp_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("WHATSAPP_API_TIMEOUT_SECONDS must be greater than 0.")
        return value

    @field_validator("jalta_sitara_hotline_language_api_timeout_seconds")
    @classmethod
    def validate_jalta_sitara_hotline_language_api_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("JALTA_SITARA_HOTLINE_LANGUAGE_API_TIMEOUT_SECONDS must be greater than 0.")
        return value

    @field_validator("jalta_sitara_hotline_base_url")
    @classmethod
    def validate_jalta_sitara_hotline_base_url(cls, value: str) -> str:
        return (value or "").rstrip("/")

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
    def default_language(self) -> str:
        """Use the first configured SUPPORTED_LANGUAGES value as the app default."""
        for item in self.supported_languages_list:
            normalized = normalize_language(item, default=None)
            if normalized:
                return normalized
        return DEFAULT_LANGUAGE

    @property
    def profile_allowed_grades_list(self) -> list[str]:
        return [item.strip() for item in self.profile_allowed_grades.split(",") if item.strip()]

    @property
    def profile_allowed_grades_casefold(self) -> set[str]:
        return {item.casefold() for item in self.profile_allowed_grades_list}

    @property
    def profile_allowed_subjects_by_grade_map(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        raw = self.profile_allowed_subjects_by_grade.strip()
        if not raw:
            return result

        for entry in raw.split(";"):
            entry = entry.strip()
            if not entry or ":" not in entry:
                continue

            grade, subjects_raw = entry.split(":", 1)
            grade = grade.strip()
            subjects = [item.strip() for item in subjects_raw.split("|") if item.strip()]
            if grade and subjects:
                result[grade] = subjects

        return result

    @property
    def profile_allowed_subjects_by_grade_casefold(self) -> dict[str, set[str]]:
        return {
            grade.casefold(): {subject.casefold() for subject in subjects}
            for grade, subjects in self.profile_allowed_subjects_by_grade_map.items()
        }

    @property
    def allow_origins_list(self) -> list[str]:
        return [item.strip() for item in self.allow_origins.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()