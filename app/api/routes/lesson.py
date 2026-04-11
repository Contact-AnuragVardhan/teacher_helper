from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.logging import get_logger, log_event
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
from app.utils.subject_normalization import normalize_subject

router = APIRouter(prefix="/lesson", tags=["lesson"])
logger = get_logger(__name__)


@router.post("/generate", response_model=LessonGenerateResponse)
def generate_lesson(payload: LessonGenerateRequest, db: Session = Depends(get_db)) -> LessonGenerateResponse:
    log_event(
        logger,
        "lesson_generate_requested",
        whatsapp_number=payload.whatsapp_number,
        topic=payload.topic,
        duration_minutes=payload.duration_minutes,
        grade=payload.grade,
        subject=payload.subject,
    )
    teacher = TeacherRepository(db).get_by_whatsapp_number(payload.whatsapp_number)
    if not teacher:
        log_event(logger, "lesson_generate_teacher_missing", whatsapp_number=payload.whatsapp_number)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found.")
    if payload.duration_minutes <= 0:
        log_event(
            logger,
            "lesson_generate_invalid_duration",
            whatsapp_number=payload.whatsapp_number,
            duration_minutes=payload.duration_minutes,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="duration_minutes must be greater than 0.",
        )

    result = LessonGeneratorService(db).generate(
        teacher=teacher,
        topic=payload.topic.strip(),
        duration_minutes=payload.duration_minutes,
        grade=payload.grade,
        subject=normalize_subject(payload.subject) if payload.subject else None,
    )
    log_event(
        logger,
        "lesson_generate_completed",
        whatsapp_number=payload.whatsapp_number,
        provider_used=result.provider_used,
        retrieved_source_count=len(result.retrieved_sources),
    )
    return LessonGenerateResponse(
        lesson_text=result.lesson_text,
        provider_used=result.provider_used,
        retrieved_sources=result.retrieved_sources,
        matched_syllabus_rows=result.matched_syllabus_rows,
    )


@router.post("/save", response_model=LessonResponse)
def save_lesson(payload: LessonSaveRequest, db: Session = Depends(get_db)) -> LessonResponse:
    log_event(
        logger,
        "lesson_save_requested",
        whatsapp_number=payload.whatsapp_number,
        lesson_name=payload.lesson_name,
        topic=payload.topic,
    )
    teacher = TeacherRepository(db).get_by_whatsapp_number(payload.whatsapp_number)
    if not teacher:
        log_event(logger, "lesson_save_teacher_missing", whatsapp_number=payload.whatsapp_number)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found.")

    if not payload.lesson_name.strip():
        log_event(logger, "lesson_save_invalid_name", whatsapp_number=payload.whatsapp_number)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="lesson_name cannot be blank.")

    repo = LessonRepository(db)
    lesson = repo.create_or_update_by_policy(
        teacher_id=teacher.id,
        lesson_name=payload.lesson_name,
        topic=payload.topic,
        grade=teacher.default_grade,
        subject=teacher.default_subject,
        duration_minutes=payload.duration_minutes,
        lesson_text=payload.lesson_text,
    )
    if lesson is None:
        log_event(
            logger,
            "lesson_save_rejected_duplicate",
            whatsapp_number=payload.whatsapp_number,
            lesson_name=payload.lesson_name,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A lesson with this name already exists.",
        )
    log_event(
        logger,
        "lesson_save_completed",
        whatsapp_number=payload.whatsapp_number,
        lesson_id=lesson.id,
        lesson_name=lesson.lesson_name,
    )
    return lesson


@router.get("/search", response_model=LessonResponse)
def search_lesson(
    whatsapp_number: str = Query(...),
    lesson_name: str = Query(...),
    db: Session = Depends(get_db),
) -> LessonResponse:
    log_event(
        logger,
        "lesson_search_requested",
        whatsapp_number=whatsapp_number,
        lesson_name=lesson_name,
    )
    teacher = TeacherRepository(db).get_by_whatsapp_number(whatsapp_number)
    if not teacher:
        log_event(logger, "lesson_search_teacher_missing", whatsapp_number=whatsapp_number)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found.")

    lesson = LessonRepository(db).get_by_teacher_and_name(teacher.id, lesson_name)
    if not lesson:
        log_event(
            logger,
            "lesson_search_not_found",
            whatsapp_number=whatsapp_number,
            lesson_name=lesson_name,
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found.")
    log_event(
        logger,
        "lesson_search_completed",
        whatsapp_number=whatsapp_number,
        lesson_id=lesson.id,
        lesson_name=lesson.lesson_name,
    )
    return lesson