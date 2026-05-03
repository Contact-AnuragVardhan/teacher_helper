from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.language import normalize_language
from app.core.logging import get_logger, log_event
from app.db.session import get_db
from app.repositories.teacher_repository import TeacherRepository
from app.schemas.teacher import TeacherResponse, TeacherUpsertRequest
from app.services.preferred_language_api_service import PreferredLanguageApiService
from app.services.subject_resolver import SubjectResolver
from app.utils.profile_validation import validate_profile_grade, validate_profile_subject
from app.utils.text import normalize_grade

router = APIRouter(prefix="/teacher", tags=["teacher"])
logger = get_logger(__name__)


@router.get("/{whatsapp_number}", response_model=TeacherResponse)
def get_teacher(whatsapp_number: str, db: Session = Depends(get_db)) -> TeacherResponse:
    log_event(logger, "teacher_fetch_requested", whatsapp_number=whatsapp_number)
    teacher_repo = TeacherRepository(db)
    teacher = teacher_repo.get_by_whatsapp_number(whatsapp_number)
    if not teacher:
        log_event(logger, "teacher_fetch_not_found", whatsapp_number=whatsapp_number)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found.")

    try:
        api_language_result = PreferredLanguageApiService(get_settings()).fetch_preferred_language(whatsapp_number)
        if api_language_result and teacher.preferred_language.casefold() != api_language_result.preferred_language.casefold():
            teacher = teacher_repo.update_preferred_language(whatsapp_number, api_language_result.preferred_language) or teacher
    except Exception as exc:  # pragma: no cover - defensive; local teacher fetch must continue.
        log_event(
            logger,
            "preferred_language_api_fetch_ignored",
            whatsapp_number=whatsapp_number,
            error=str(exc),
        )

    log_event(logger, "teacher_fetch_completed", whatsapp_number=whatsapp_number, teacher_id=teacher.id)
    return teacher


@router.post("", response_model=TeacherResponse)
def upsert_teacher(payload: TeacherUpsertRequest, db: Session = Depends(get_db)) -> TeacherResponse:
    settings = get_settings()
    raw_language = (payload.preferred_language or "").strip()
    preferred_language = (
        normalize_language(raw_language, default=None)
        if raw_language
        else settings.default_language
    )

    preferred_language_api = PreferredLanguageApiService(settings)

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

    normalized_grade = normalize_grade(payload.default_grade)
    grade_error = validate_profile_grade(normalized_grade, settings)
    if grade_error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=grade_error)

    normalized_subject = SubjectResolver(settings).resolve(payload.default_subject, language=preferred_language)

    subject_error = validate_profile_subject(
        normalized_subject,
        normalized_grade,
        settings,
    )
    if subject_error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=subject_error)

    # The /teacher upsert request is an explicit profile create/edit. Save the
    # requested language locally first, then update Jalta Sitara Hotline if needed.
    # Hotline sync is best-effort and must never block local profile create/update.
    teacher = TeacherRepository(db).upsert(
        whatsapp_number=payload.whatsapp_number,
        teacher_name=payload.teacher_name.strip(),
        default_grade=normalized_grade,
        default_subject=normalized_subject,
        preferred_language=preferred_language,
    )
    try:
        preferred_language_api.sync_preferred_language_if_needed(
            phone_number=payload.whatsapp_number,
            selected_language=preferred_language,
        )
    except Exception as exc:  # pragma: no cover - defensive; local upsert already succeeded.
        log_event(
            logger,
            "preferred_language_sync_ignored",
            whatsapp_number=payload.whatsapp_number,
            preferred_language=preferred_language,
            error=str(exc),
        )
    log_event(logger, "teacher_upsert_completed", whatsapp_number=payload.whatsapp_number, teacher_id=teacher.id)
    return teacher
