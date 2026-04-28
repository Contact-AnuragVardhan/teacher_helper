from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.language import DEFAULT_LANGUAGE


class TeacherUpsertRequest(BaseModel):
    whatsapp_number: str
    teacher_name: str
    default_grade: str
    default_subject: str
    preferred_language: str = DEFAULT_LANGUAGE


class TeacherResponse(BaseModel):
    id: int
    whatsapp_number: str
    teacher_name: str
    default_grade: str
    default_subject: str
    preferred_language: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
