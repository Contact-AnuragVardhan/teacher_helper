from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger, log_event
from app.models.lesson_plan import LessonPlan

logger = get_logger(__name__)


class LessonRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_teacher_and_name(self, teacher_id: int, lesson_name: str) -> LessonPlan | None:
        normalized_name = lesson_name.strip().lower()
        lesson = (
            self.db.query(LessonPlan)
            .filter(
                LessonPlan.teacher_id == teacher_id,
                func.lower(LessonPlan.lesson_name) == normalized_name,
            )
            .first()
        )
        log_event(
            logger,
            "lesson_lookup",
            teacher_id=teacher_id,
            lesson_name=lesson_name,
            found=lesson is not None,
        )
        return lesson

    def list_titles_by_teacher(self, teacher_id: int) -> list[str]:
        rows = (
            self.db.query(LessonPlan.lesson_name)
            .filter(LessonPlan.teacher_id == teacher_id)
            .order_by(func.lower(LessonPlan.lesson_name))
            .all()
        )
        titles = [row[0] for row in rows]
        log_event(
            logger,
            "lesson_titles_listed",
            teacher_id=teacher_id,
            count=len(titles),
        )
        return titles

    def create(
        self,
        *,
        teacher_id: int,
        lesson_name: str,
        topic: str,
        grade: str,
        subject: str,
        duration_minutes: int,
        lesson_text: str,
    ) -> LessonPlan:
        lesson = LessonPlan(
            teacher_id=teacher_id,
            lesson_name=lesson_name.strip(),
            topic=topic.strip(),
            grade=grade.strip(),
            subject=subject.strip(),
            duration_minutes=duration_minutes,
            lesson_text=lesson_text,
        )
        self.db.add(lesson)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            log_event(
                logger,
                "lesson_create_integrity_error",
                teacher_id=teacher_id,
                lesson_name=lesson_name,
            )
            raise
        self.db.refresh(lesson)
        log_event(
            logger,
            "lesson_created",
            teacher_id=teacher_id,
            lesson_id=lesson.id,
            lesson_name=lesson.lesson_name,
        )
        return lesson

    def overwrite(
        self,
        lesson: LessonPlan,
        *,
        topic: str,
        grade: str,
        subject: str,
        duration_minutes: int,
        lesson_text: str,
    ) -> LessonPlan:
        lesson.topic = topic.strip()
        lesson.grade = grade.strip()
        lesson.subject = subject.strip()
        lesson.duration_minutes = duration_minutes
        lesson.lesson_text = lesson_text
        self.db.add(lesson)
        self.db.commit()
        self.db.refresh(lesson)
        log_event(
            logger,
            "lesson_overwritten",
            teacher_id=lesson.teacher_id,
            lesson_id=lesson.id,
            lesson_name=lesson.lesson_name,
        )
        return lesson

    def create_or_update_by_policy(
        self,
        *,
        teacher_id: int,
        lesson_name: str,
        topic: str,
        grade: str,
        subject: str,
        duration_minutes: int,
        lesson_text: str,
    ) -> LessonPlan | None:
        settings = get_settings()
        existing = self.get_by_teacher_and_name(teacher_id, lesson_name)
        if existing:
            if settings.duplicate_lesson_policy == "reject":
                log_event(
                    logger,
                    "lesson_duplicate_rejected",
                    teacher_id=teacher_id,
                    lesson_name=lesson_name,
                )
                return None
            log_event(
                logger,
                "lesson_duplicate_overwrite",
                teacher_id=teacher_id,
                lesson_name=lesson_name,
            )
            return self.overwrite(
                existing,
                topic=topic,
                grade=grade,
                subject=subject,
                duration_minutes=duration_minutes,
                lesson_text=lesson_text,
            )

        log_event(
            logger,
            "lesson_create_by_policy",
            teacher_id=teacher_id,
            lesson_name=lesson_name,
        )
        return self.create(
            teacher_id=teacher_id,
            lesson_name=lesson_name,
            topic=topic,
            grade=grade,
            subject=subject,
            duration_minutes=duration_minutes,
            lesson_text=lesson_text,
        )