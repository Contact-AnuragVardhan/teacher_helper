from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger, log_event
from app.models.lesson_plan import LessonPlan
from app.models.lesson_share import LessonShare
from app.models.teacher_profile import TeacherProfile
from app.utils.subject_normalization import normalize_subject

logger = get_logger(__name__)


@dataclass
class AccessibleLessonSummary:
    lesson_id: int
    lesson_name: str
    display_title: str
    is_shared: bool
    topic: str | None = None
    shared_by_teacher_id: int | None = None
    shared_by_teacher_name: str | None = None


@dataclass
class AccessibleLesson:
    lesson: LessonPlan
    is_shared: bool
    shared_by_teacher_id: int | None = None
    shared_by_teacher_name: str | None = None


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

    def get_by_teacher_and_id(self, teacher_id: int, lesson_id: int) -> LessonPlan | None:
        lesson = (
            self.db.query(LessonPlan)
            .filter(
                LessonPlan.teacher_id == teacher_id,
                LessonPlan.id == lesson_id,
            )
            .first()
        )
        log_event(
            logger,
            "lesson_lookup_by_id",
            teacher_id=teacher_id,
            lesson_id=lesson_id,
            found=lesson is not None,
        )
        return lesson

    def get_accessible_lesson_by_teacher_and_id(self, teacher_id: int, lesson_id: int) -> AccessibleLesson | None:
        owned_lesson = self.get_by_teacher_and_id(teacher_id, lesson_id)
        if owned_lesson:
            return AccessibleLesson(lesson=owned_lesson, is_shared=False)

        shared = (
            self.db.query(LessonPlan, LessonShare, TeacherProfile)
            .join(LessonShare, LessonShare.lesson_id == LessonPlan.id)
            .join(TeacherProfile, TeacherProfile.id == LessonShare.shared_by_teacher_id)
            .filter(
                LessonPlan.id == lesson_id,
                LessonShare.shared_with_teacher_id == teacher_id,
            )
            .first()
        )
        if not shared:
            return None

        lesson, share, shared_by_teacher = shared
        return AccessibleLesson(
            lesson=lesson,
            is_shared=True,
            shared_by_teacher_id=share.shared_by_teacher_id,
            shared_by_teacher_name=shared_by_teacher.teacher_name,
        )

    def list_titles_by_teacher(self, teacher_id: int) -> list[str]:
        return [item.lesson_name for item in self.list_accessible_summaries_for_teacher(teacher_id)]

    def list_summaries_by_teacher(self, teacher_id: int) -> list[tuple[int, str]]:
        return [
            (item.lesson_id, item.display_title)
            for item in self.list_accessible_summaries_for_teacher(teacher_id)
        ]

    def list_accessible_summaries_for_teacher(self, teacher_id: int) -> list[AccessibleLessonSummary]:
        owned_rows = (
            self.db.query(LessonPlan.id, LessonPlan.lesson_name, LessonPlan.topic)
            .filter(LessonPlan.teacher_id == teacher_id)
            .all()
        )
        shared_rows = (
            self.db.query(
                LessonPlan.id,
                LessonPlan.lesson_name,
                LessonPlan.topic,
                LessonShare.shared_by_teacher_id,
                TeacherProfile.teacher_name,
            )
            .join(LessonShare, LessonShare.lesson_id == LessonPlan.id)
            .join(TeacherProfile, TeacherProfile.id == LessonShare.shared_by_teacher_id)
            .filter(LessonShare.shared_with_teacher_id == teacher_id)
            .all()
        )

        summaries = [
            AccessibleLessonSummary(
                lesson_id=row[0],
                lesson_name=row[1],
                display_title=row[1],
                is_shared=False,
                topic=row[2],
            )
            for row in owned_rows
        ]
        summaries.extend(
            AccessibleLessonSummary(
                lesson_id=row[0],
                lesson_name=row[1],
                display_title=f"* {row[1]}",
                is_shared=True,
                topic=row[2],
                shared_by_teacher_id=row[3],
                shared_by_teacher_name=row[4],
            )
            for row in shared_rows
        )
        summaries.sort(key=lambda item: item.display_title.casefold())

        log_event(
            logger,
            "lesson_accessible_summaries_listed",
            teacher_id=teacher_id,
            count=len(summaries),
            shared_count=sum(1 for item in summaries if item.is_shared),
        )
        return summaries

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
        lesson_payload: dict | None,
    ) -> LessonPlan:
        lesson = LessonPlan(
            teacher_id=teacher_id,
            lesson_name=lesson_name.strip(),
            topic=topic.strip(),
            grade=grade.strip(),
            subject=normalize_subject(subject),
            duration_minutes=duration_minutes,
            lesson_text=lesson_text,
            lesson_payload=lesson_payload,
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
        lesson_payload: dict | None,
    ) -> LessonPlan:
        lesson.topic = topic.strip()
        lesson.grade = grade.strip()
        lesson.subject = normalize_subject(subject)
        lesson.duration_minutes = duration_minutes
        lesson.lesson_text = lesson_text
        lesson.lesson_payload = lesson_payload
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
        lesson_payload: dict | None,
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
                lesson_payload=lesson_payload,
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
            lesson_payload=lesson_payload,
        )

    def delete_owned_lesson(self, teacher_id: int, lesson_id: int) -> bool:
        lesson = self.get_by_teacher_and_id(teacher_id, lesson_id)
        if not lesson:
            return False

        self.db.delete(lesson)
        self.db.commit()
        log_event(
            logger,
            "lesson_deleted",
            teacher_id=teacher_id,
            lesson_id=lesson_id,
        )
        return True

    def share_owned_lesson(
        self,
        *,
        lesson_id: int,
        owner_teacher_id: int,
        shared_with_teacher_id: int,
    ) -> LessonShare | None:
        lesson = self.get_by_teacher_and_id(owner_teacher_id, lesson_id)
        if lesson is None:
            log_event(
                logger,
                "lesson_share_not_allowed",
                lesson_id=lesson_id,
                owner_teacher_id=owner_teacher_id,
                shared_with_teacher_id=shared_with_teacher_id,
            )
            return None

        share = (
            self.db.query(LessonShare)
            .filter(
                LessonShare.lesson_id == lesson_id,
                LessonShare.shared_with_teacher_id == shared_with_teacher_id,
            )
            .first()
        )
        action = "updated" if share else "created"

        if share is None:
            share = LessonShare(
                lesson_id=lesson_id,
                shared_by_teacher_id=owner_teacher_id,
                shared_with_teacher_id=shared_with_teacher_id,
            )
            self.db.add(share)
        else:
            share.shared_by_teacher_id = owner_teacher_id

        self.db.commit()
        self.db.refresh(share)
        log_event(
            logger,
            "lesson_shared",
            lesson_id=lesson_id,
            shared_by_teacher_id=owner_teacher_id,
            shared_with_teacher_id=shared_with_teacher_id,
            action=action,
        )
        return share
