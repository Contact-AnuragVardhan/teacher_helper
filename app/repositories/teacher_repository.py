from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.language import normalize_language
from app.core.logging import get_logger, log_event
from app.models.teacher_profile import TeacherProfile
from app.utils.subject_normalization import normalize_subject

logger = get_logger(__name__)


class TeacherRepository:
    def __init__(self, db: Session):
        self.db = db

    def _digits_only(self, phone_number: str) -> str:
        return "".join(ch for ch in (phone_number or "") if ch.isdigit())

    def _canonical_whatsapp_number(self, phone_number: str) -> str:
        digits = self._digits_only(phone_number)
        return f"+{digits}" if digits else ""

    def get_by_whatsapp_number(self, whatsapp_number: str) -> TeacherProfile | None:
        canonical_number = self._canonical_whatsapp_number(whatsapp_number)
        digits_only = self._digits_only(whatsapp_number)

        if not digits_only:
            log_event(
                logger,
                "teacher_lookup",
                whatsapp_number=whatsapp_number,
                canonical_number=canonical_number,
                found=False,
            )
            return None

        teacher = (
            self.db.query(TeacherProfile)
            .filter(
                or_(
                    TeacherProfile.whatsapp_number == canonical_number,
                    TeacherProfile.whatsapp_number == digits_only,
                    func.replace(TeacherProfile.whatsapp_number, "+", "") == digits_only,
                )
            )
            .first()
        )

        log_event(
            logger,
            "teacher_lookup",
            whatsapp_number=whatsapp_number,
            canonical_number=canonical_number,
            found=teacher is not None,
        )
        return teacher


    def update_preferred_language(
        self,
        whatsapp_number: str,
        preferred_language: str,
    ) -> TeacherProfile | None:
        teacher = self.get_by_whatsapp_number(whatsapp_number)
        if not teacher:
            return None

        settings = get_settings()
        normalized_language = normalize_language((preferred_language or "").strip(), default=None)
        if not normalized_language or normalized_language.casefold() not in settings.supported_languages_casefold:
            log_event(
                logger,
                "teacher_language_sync_skipped_invalid_language",
                whatsapp_number=whatsapp_number,
                preferred_language=preferred_language,
            )
            return teacher

        current_language = (teacher.preferred_language or "").strip()
        if current_language.casefold() == normalized_language.casefold():
            return teacher

        teacher.preferred_language = normalized_language
        self.db.commit()
        self.db.refresh(teacher)

        log_event(
            logger,
            "teacher_language_synced",
            whatsapp_number=teacher.whatsapp_number,
            teacher_id=teacher.id,
            old_language=current_language,
            new_language=normalized_language,
        )
        return teacher

    def upsert(
        self,
        *,
        whatsapp_number: str,
        teacher_name: str,
        default_grade: str,
        default_subject: str,
        preferred_language: str,
    ) -> TeacherProfile:
        canonical_number = self._canonical_whatsapp_number(whatsapp_number)
        teacher = self.get_by_whatsapp_number(canonical_number)
        action = "updated" if teacher else "created"
        normalized_subject = normalize_subject(default_subject)
        settings = get_settings()
        preferred_language_value = (preferred_language or "").strip()
        normalized_language = (
            normalize_language(preferred_language_value, default=None)
            if preferred_language_value
            else settings.default_language
        )
        normalized_language = normalized_language or settings.default_language

        if teacher:
            teacher.whatsapp_number = canonical_number or teacher.whatsapp_number
            teacher.teacher_name = teacher_name
            teacher.default_grade = default_grade
            teacher.default_subject = normalized_subject
            teacher.preferred_language = normalized_language
        else:
            teacher = TeacherProfile(
                whatsapp_number=canonical_number,
                teacher_name=teacher_name,
                default_grade=default_grade,
                default_subject=normalized_subject,
                preferred_language=normalized_language,
            )
            self.db.add(teacher)

        self.db.commit()
        self.db.refresh(teacher)
        log_event(
            logger,
            "teacher_upsert_persisted",
            whatsapp_number=canonical_number,
            teacher_id=teacher.id,
            action=action,
            preferred_language=normalized_language,
        )
        return teacher
