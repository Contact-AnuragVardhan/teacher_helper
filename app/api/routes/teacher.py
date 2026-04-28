from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.language import normalize_language
from app.core.logging import get_logger, log_event
from app.db.session import get_db
from app.repositories.teacher_repository import TeacherRepository
from app.schemas.teacher import TeacherResponse, TeacherUpsertRequest
from app.utils.profile_validation import validate_profile_grade, validate_profile_subject
from app.utils.subject_normalization import normalize_subject

router = APIRouter(prefix="/teacher", tags=["teacher"])
logger = get_logger(__name__)


@router.get("/{whatsapp_number}", response_model=TeacherResponse)
def get_teacher(whatsapp_number: str, db: Session = Depends(get_db)) -> TeacherResponse:
    log_event(logger, "teacher_fetch_requested", whatsapp_number=whatsapp_number)
    teacher = TeacherRepository(db).get_by_whatsapp_number(whatsapp_number)
    if not teacher:
        log_event(logger, "teacher_fetch_not_found", whatsapp_number=whatsapp_number)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found.")
    log_event(logger, "teacher_fetch_completed", whatsapp_number=whatsapp_number, teacher_id=teacher.id)
    return teacher


@router.post("", response_model=TeacherResponse)
def upsert_teacher(payload: TeacherUpsertRequest, db: Session = Depends(get_db)) -> TeacherResponse:
    settings = get_settings()
    preferred_language = normalize_language(payload.preferred_language, default=None)

    log_event(
        logger,
        "teacher_upsert_requested",
        whatsapp_number=payload.whatsapp_number,
        default_grade=payload.default_grade,
        default_subject=payload.default_subject,
        preferred_language=payload.preferred_language,
        normalized_language=preferred_language,
    )

    if not preferred_language or preferred_language.casefold() not in settings.supported_languages_casefold:
        log_event(
            logger,
            "teacher_upsert_invalid_language",
            whatsapp_number=payload.whatsapp_number,
            preferred_language=payload.preferred_language,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"preferred_language must be one of: {', '.join(settings.supported_languages_list)}.",
        )

    grade_error = validate_profile_grade(payload.default_grade, settings)
    if grade_error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=grade_error)

    normalized_subject = normalize_subject(payload.default_subject)

    subject_error = validate_profile_subject(
        normalized_subject,
        payload.default_grade,
        settings,
    )
    if subject_error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=subject_error)

    teacher = TeacherRepository(db).upsert(
        whatsapp_number=payload.whatsapp_number,
        teacher_name=payload.teacher_name.strip(),
        default_grade=payload.default_grade.strip(),
        default_subject=normalized_subject,
        preferred_language=preferred_language,
    )
    log_event(logger, "teacher_upsert_completed", whatsapp_number=payload.whatsapp_number, teacher_id=teacher.id)
    return teacher
