from sqlalchemy.orm import Session

from app.core.logging import get_logger, log_event
from app.models.teacher_profile import TeacherProfile
from app.utils.subject_normalization import normalize_subject

logger = get_logger(__name__)


class TeacherRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_whatsapp_number(self, whatsapp_number: str) -> TeacherProfile | None:
        teacher = (
            self.db.query(TeacherProfile)
            .filter(TeacherProfile.whatsapp_number == whatsapp_number)
            .first()
        )
        log_event(
            logger,
            "teacher_lookup",
            whatsapp_number=whatsapp_number,
            found=teacher is not None,
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
        teacher = self.get_by_whatsapp_number(whatsapp_number)
        action = "updated" if teacher else "created"
        normalized_subject = normalize_subject(default_subject)
        if teacher:
            teacher.teacher_name = teacher_name
            teacher.default_grade = default_grade
            teacher.default_subject = normalized_subject
            teacher.preferred_language = preferred_language
        else:
            teacher = TeacherProfile(
                whatsapp_number=whatsapp_number,
                teacher_name=teacher_name,
                default_grade=default_grade,
                default_subject=normalized_subject,
                preferred_language=preferred_language,
            )
            self.db.add(teacher)

        self.db.commit()
        self.db.refresh(teacher)
        log_event(
            logger,
            "teacher_upsert_persisted",
            whatsapp_number=whatsapp_number,
            teacher_id=teacher.id,
            action=action,
        )
        return teacher
