from sqlalchemy.orm import Session

from app.models.teacher_profile import TeacherProfile


class TeacherRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_whatsapp_number(self, whatsapp_number: str) -> TeacherProfile | None:
        return (
            self.db.query(TeacherProfile)
            .filter(TeacherProfile.whatsapp_number == whatsapp_number)
            .first()
        )

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
        if teacher:
            teacher.teacher_name = teacher_name
            teacher.default_grade = default_grade
            teacher.default_subject = default_subject
            teacher.preferred_language = preferred_language
        else:
            teacher = TeacherProfile(
                whatsapp_number=whatsapp_number,
                teacher_name=teacher_name,
                default_grade=default_grade,
                default_subject=default_subject,
                preferred_language=preferred_language,
            )
            self.db.add(teacher)

        self.db.commit()
        self.db.refresh(teacher)
        return teacher
