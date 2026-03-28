from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.lesson_repository import LessonRepository
from app.repositories.teacher_repository import TeacherRepository
from app.schemas.lesson import (
    LessonGenerateRequest,
    LessonGenerateResponse,
    LessonResponse,
    LessonSaveRequest,
)
from app.services.lesson_generator import LessonGeneratorService

router = APIRouter(prefix="/lesson", tags=["lesson"])


@router.post("/generate", response_model=LessonGenerateResponse)
def generate_lesson(payload: LessonGenerateRequest, db: Session = Depends(get_db)) -> LessonGenerateResponse:
    teacher = TeacherRepository(db).get_by_whatsapp_number(payload.whatsapp_number)
    if not teacher:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found.")
    if payload.duration_minutes <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="duration_minutes must be greater than 0.",
        )
    lesson_text = LessonGeneratorService().generate(
        teacher=teacher,
        topic=payload.topic.strip(),
        duration_minutes=payload.duration_minutes,
    )
    return LessonGenerateResponse(lesson_text=lesson_text)


@router.post("/save", response_model=LessonResponse)
def save_lesson(payload: LessonSaveRequest, db: Session = Depends(get_db)) -> LessonResponse:
    teacher = TeacherRepository(db).get_by_whatsapp_number(payload.whatsapp_number)
    if not teacher:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found.")

    if not payload.lesson_name.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="lesson_name cannot be blank.")

    repo = LessonRepository(db)
    if repo.get_by_teacher_and_name(teacher.id, payload.lesson_name):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A lesson with this name already exists.",
        )

    try:
        lesson = repo.create(
            teacher_id=teacher.id,
            lesson_name=payload.lesson_name,
            topic=payload.topic,
            grade=teacher.default_grade,
            subject=teacher.default_subject,
            duration_minutes=payload.duration_minutes,
            lesson_text=payload.lesson_text,
        )
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A lesson with this name already exists.",
        ) from None

    return lesson


@router.get("/search", response_model=LessonResponse)
def search_lesson(
    whatsapp_number: str = Query(...),
    lesson_name: str = Query(...),
    db: Session = Depends(get_db),
) -> LessonResponse:
    teacher = TeacherRepository(db).get_by_whatsapp_number(whatsapp_number)
    if not teacher:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found.")

    lesson = LessonRepository(db).get_by_teacher_and_name(teacher.id, lesson_name)
    if not lesson:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found.")
    return lesson
