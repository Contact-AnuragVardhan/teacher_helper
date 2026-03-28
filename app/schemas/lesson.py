from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LessonGenerateRequest(BaseModel):
    whatsapp_number: str
    topic: str
    duration_minutes: int


class LessonGenerateResponse(BaseModel):
    lesson_text: str


class LessonSaveRequest(BaseModel):
    whatsapp_number: str
    lesson_name: str
    topic: str
    duration_minutes: int
    lesson_text: str


class LessonResponse(BaseModel):
    id: int
    lesson_name: str
    topic: str
    grade: str
    subject: str
    duration_minutes: int
    lesson_text: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
