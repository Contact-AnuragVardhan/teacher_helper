from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.utils.text import parse_duration_minutes


class LessonGenerateRequest(BaseModel):
    whatsapp_number: str
    topic: str
    duration_minutes: int
    grade: str | None = None
    subject: str | None = None

    @field_validator("duration_minutes", mode="before")
    @classmethod
    def parse_duration(cls, value):
        minutes = parse_duration_minutes(value)
        if minutes is None:
            raise ValueError("duration_minutes must be greater than 0.")
        return minutes


class SyllabusMatchResponse(BaseModel):
    id: int
    grade: str
    subject: str
    book: str | None = None
    book_url: str | None = None
    chapter: str | None = None
    unit_name: str | None = None
    topic_name: str | None = None
    topic_summary: str | None = None
    lesson_goal: str | None = None
    keywords: str | None = None
    source_reference: str | None = None
    score: int
    exact_matches: list[str] = Field(default_factory=list)
    partial_matches: list[str] = Field(default_factory=list)


class LessonGenerateResponse(BaseModel):
    lesson_text: str
    provider_used: str | None = None
    retrieved_sources: list[str] = Field(default_factory=list)
    matched_syllabus_rows: list[SyllabusMatchResponse] = Field(default_factory=list)


class LessonSaveRequest(BaseModel):
    whatsapp_number: str
    lesson_name: str
    topic: str
    duration_minutes: int
    lesson_text: str

    @field_validator("duration_minutes", mode="before")
    @classmethod
    def parse_duration(cls, value):
        minutes = parse_duration_minutes(value)
        if minutes is None:
            raise ValueError("duration_minutes must be greater than 0.")
        return minutes


class LessonResponse(BaseModel):
    id: int
    lesson_name: str
    topic: str
    grade: str
    subject: str
    duration_minutes: int
    lesson_text: str
    lesson_payload: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
