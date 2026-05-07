from datetime import UTC, datetime
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger, log_event
from app.db.session import get_db
from app.models.lesson_plan import LessonPlan
from app.models.teacher_profile import TeacherProfile
from app.services.subject_resolver import SubjectResolver
from app.utils.subject_normalization import normalize_subject
from app.utils.text import normalize_grade, parse_duration_minutes

router = APIRouter(prefix="/api/library", tags=["library"])
logger = get_logger(__name__)


class SaveLibraryLessonRequest(BaseModel):
    teacher_id: str
    lesson_name: str
    grade: str
    subject: str
    topic: str
    duration_minutes: int

    @field_validator("duration_minutes", mode="before")
    @classmethod
    def parse_duration(cls, value):
        minutes = parse_duration_minutes(value)
        if minutes is None:
            raise ValueError("duration_minutes must be greater than 0.")
        return minutes
    source_type: str | None = None
    source_reference: dict[str, Any] | None = None
    lesson_json: dict[str, Any]


class UpdateLibraryLessonRequest(BaseModel):
    lesson_name: str | None = None
    lesson_json: dict[str, Any] | None = None
    source_type: str | None = None
    source_reference: dict[str, Any] | None = None


def _parse_teacher_id(value: str) -> int:
    raw = value.strip()
    if raw.isdigit():
        return int(raw)
    match = re.fullmatch(r"teacher-(\d+)", raw, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="teacher_id must be an integer id or formatted like teacher-001.",
    )


def _parse_lesson_id(value: str) -> int:
    raw = value.strip()
    if raw.isdigit():
        return int(raw)
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="lesson_id must be a numeric id.",
    )


def _format_teacher_id(teacher_id: int) -> str:
    return f"teacher-{teacher_id:03d}"


def _get_teacher_or_404(db: Session, teacher_id_value: str) -> TeacherProfile:
    teacher_id = _parse_teacher_id(teacher_id_value)
    teacher = db.query(TeacherProfile).filter(TeacherProfile.id == teacher_id).first()
    if not teacher:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found.")
    return teacher


def _build_source_reference(
    grade: str,
    subject: str,
    topic: str,
    source_reference: dict[str, Any] | None,
) -> dict[str, Any]:
    if source_reference:
        return source_reference
    return {
        "grade": grade.strip(),
        "subject": normalize_subject(subject),
        "topic_name": topic.strip(),
    }


def _build_lesson_text(lesson_json: dict[str, Any]) -> str:
    def as_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            return "\n".join(f"- {str(item).strip()}" for item in value if str(item).strip())
        return str(value).strip()

    lines: list[str] = ["Lesson Planning"]

    ordered_fields = [
        ("lesson_title", "Lesson Title"),
        ("objective", "Objective"),
        ("opening", "Opening"),
        ("main_teaching", "Main Teaching"),
        ("activity", "Activity"),
        ("qa", "Q&A"),
        ("closing", "Closing"),
    ]

    for key, label in ordered_fields:
        if key not in lesson_json:
            continue
        value = lesson_json.get(key)
        rendered = as_text(value)
        if not rendered:
            continue
        lines.append(f"{label}:")
        lines.append(rendered)
        lines.append("")

    return "\n".join(lines).strip()


def _build_lesson_payload(
    *,
    lesson: LessonPlan,
    teacher: TeacherProfile,
    source_type: str | None,
    source_reference: dict[str, Any],
    lesson_json: dict[str, Any],
) -> dict[str, Any]:
    created_at = lesson.created_at or datetime.now(UTC)
    updated_at = lesson.updated_at or datetime.now(UTC)
    return {
        "lesson_id": str(lesson.id),
        "teacher_id": _format_teacher_id(teacher.id),
        "lesson_name": lesson.lesson_name,
        "grade": lesson.grade,
        "subject": lesson.subject,
        "topic": lesson.topic,
        "duration_minutes": lesson.duration_minutes,
        "source_type": source_type or "generated",
        "source_reference": source_reference,
        "lesson_json": lesson_json,
        "metadata": {
            "difficulty": "normal",
            "language": teacher.preferred_language,
            "created_by": "Teacher Helper API",
            "created_at": created_at.isoformat(),
            "updated_at": updated_at.isoformat(),
            "version": 1,
        },
    }


def _set_lesson_payload(lesson: LessonPlan, payload: dict[str, Any]) -> None:
    if hasattr(lesson, "lesson_payload"):
        setattr(lesson, "lesson_payload", payload)


def _get_lesson_payload(lesson: LessonPlan) -> dict[str, Any] | None:
    if hasattr(lesson, "lesson_payload"):
        payload = getattr(lesson, "lesson_payload")
        if isinstance(payload, dict):
            return payload
    return None


def _lesson_response(lesson: LessonPlan, teacher: TeacherProfile | None = None) -> dict[str, Any]:
    teacher_obj = teacher or lesson.teacher
    stored_payload = _get_lesson_payload(lesson)
    if stored_payload:
        lesson_json = stored_payload.get("lesson_json") or {}
        source_type = stored_payload.get("source_type")
        source_reference = stored_payload.get("source_reference") or {}
        teacher_id_value = stored_payload.get("teacher_id") or _format_teacher_id(lesson.teacher_id)
    else:
        lesson_json = {"raw_lesson_text": lesson.lesson_text}
        source_type = None
        source_reference = {}
        teacher_id_value = _format_teacher_id(lesson.teacher_id)

    return {
        "lesson_id": str(lesson.id),
        "teacher_id": teacher_id_value,
        "lesson_name": lesson.lesson_name,
        "grade": lesson.grade,
        "subject": lesson.subject,
        "topic": lesson.topic,
        "duration_minutes": lesson.duration_minutes,
        "source_type": source_type,
        "source_reference": source_reference,
        "lesson_json": lesson_json,
        "created_at": lesson.created_at.isoformat(),
        "updated_at": lesson.updated_at.isoformat(),
        "language": teacher_obj.preferred_language if teacher_obj else None,
    }


@router.post("/lessons")
def save_library_lesson(payload: SaveLibraryLessonRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    log_event(
        logger,
        "library_lesson_save_requested",
        teacher_id=payload.teacher_id,
        lesson_name=payload.lesson_name,
        topic=payload.topic,
    )

    if payload.duration_minutes <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="duration_minutes must be greater than 0.",
        )

    teacher = _get_teacher_or_404(db, payload.teacher_id)
    settings = get_settings()
    normalized_grade = normalize_grade(payload.grade)
    normalized_subject = SubjectResolver(settings).resolve(payload.subject, language=teacher.preferred_language)
    source_reference = _build_source_reference(
        normalized_grade,
        normalized_subject,
        payload.topic,
        payload.source_reference,
    )
    lesson_text = _build_lesson_text(payload.lesson_json)

    existing = (
        db.query(LessonPlan)
        .filter(
            LessonPlan.teacher_id == teacher.id,
            func.lower(LessonPlan.lesson_name) == payload.lesson_name.strip().lower(),
        )
        .first()
    )

    if existing and settings.duplicate_lesson_policy == "reject":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A lesson with this name already exists for this teacher.",
        )

    lesson = existing or LessonPlan(teacher_id=teacher.id)
    lesson.lesson_name = payload.lesson_name.strip()
    lesson.topic = payload.topic.strip()
    lesson.grade = normalized_grade
    lesson.subject = normalized_subject
    lesson.duration_minutes = payload.duration_minutes
    lesson.lesson_text = lesson_text

    if existing is None:
        db.add(lesson)
        db.flush()

    lesson_payload = _build_lesson_payload(
        lesson=lesson,
        teacher=teacher,
        source_type=payload.source_type,
        source_reference=source_reference,
        lesson_json=payload.lesson_json,
    )
    _set_lesson_payload(lesson, lesson_payload)

    db.commit()
    db.refresh(lesson)

    log_event(
        logger,
        "library_lesson_save_completed",
        teacher_id=teacher.id,
        lesson_id=lesson.id,
        action="updated" if existing else "created",
    )
    return {"success": True, "lesson_id": str(lesson.id)}


@router.get("/lessons/{lesson_id}")
def get_library_lesson(lesson_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    lesson_id_int = _parse_lesson_id(lesson_id)
    log_event(logger, "library_lesson_get_requested", lesson_id=lesson_id_int)

    lesson = db.query(LessonPlan).filter(LessonPlan.id == lesson_id_int).first()
    if not lesson:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found.")

    teacher = db.query(TeacherProfile).filter(TeacherProfile.id == lesson.teacher_id).first()
    response = _lesson_response(lesson, teacher)
    log_event(logger, "library_lesson_get_completed", lesson_id=lesson.id)
    return response


@router.get("/search")
def search_library_lessons(
    teacher_id: str | None = Query(None),
    lesson_name: str | None = None,
    grade: str | None = None,
    subject: str | None = None,
    topic: str | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    teacher = None

    log_event(
        logger,
        "library_lesson_search_requested",
        teacher_id=teacher_id,
        lesson_name=lesson_name,
        grade=grade,
        subject=subject,
        topic=topic,
    )

    query = db.query(LessonPlan)

    if teacher_id:
        teacher = _get_teacher_or_404(db, teacher_id)
        query = query.filter(LessonPlan.teacher_id == teacher.id)

    if lesson_name:
        query = query.filter(func.lower(LessonPlan.lesson_name) == lesson_name.strip().lower())
    if grade:
        query = query.filter(LessonPlan.grade == grade.strip())
    if subject:
        query = query.filter(LessonPlan.subject == normalize_subject(subject))
    if topic:
        query = query.filter(func.lower(LessonPlan.topic) == topic.strip().lower())

    rows = query.order_by(LessonPlan.updated_at.desc(), LessonPlan.id.desc()).all()

    items = [
        {
            "lesson_id": str(row.id),
            "teacher_id": _format_teacher_id(row.teacher_id),
            "lesson_name": row.lesson_name,
            "grade": row.grade,
            "subject": row.subject,
            "topic": row.topic,
            "duration_minutes": row.duration_minutes,
            "updated_at": row.updated_at.isoformat(),
        }
        for row in rows
    ]

    log_event(
        logger,
        "library_lesson_search_completed",
        teacher_id=teacher.id if teacher else None,
        count=len(items),
    )
    return {"count": len(items), "items": items}


@router.put("/lessons/{lesson_id}")
def update_library_lesson(
    lesson_id: str,
    payload: UpdateLibraryLessonRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    lesson_id_int = _parse_lesson_id(lesson_id)
    log_event(logger, "library_lesson_update_requested", lesson_id=lesson_id_int)

    lesson = db.query(LessonPlan).filter(LessonPlan.id == lesson_id_int).first()
    if not lesson:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found.")

    teacher = db.query(TeacherProfile).filter(TeacherProfile.id == lesson.teacher_id).first()
    if not teacher:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found.")

    stored_payload = _get_lesson_payload(lesson) or {}
    current_lesson_json = stored_payload.get("lesson_json") or {"raw_lesson_text": lesson.lesson_text}
    current_source_reference = stored_payload.get("source_reference") or _build_source_reference(
        lesson.grade,
        lesson.subject,
        lesson.topic,
        None,
    )
    current_source_type = stored_payload.get("source_type")

    if payload.lesson_name is not None and not payload.lesson_name.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="lesson_name cannot be blank.")

    if payload.lesson_name is not None:
        lesson.lesson_name = payload.lesson_name.strip()

    next_lesson_json = payload.lesson_json if payload.lesson_json is not None else current_lesson_json
    next_source_type = payload.source_type if payload.source_type is not None else current_source_type
    next_source_reference = payload.source_reference if payload.source_reference is not None else current_source_reference

    lesson.lesson_text = _build_lesson_text(next_lesson_json)

    lesson_payload = _build_lesson_payload(
        lesson=lesson,
        teacher=teacher,
        source_type=next_source_type,
        source_reference=next_source_reference,
        lesson_json=next_lesson_json,
    )
    _set_lesson_payload(lesson, lesson_payload)

    db.add(lesson)
    db.commit()
    db.refresh(lesson)

    log_event(logger, "library_lesson_update_completed", lesson_id=lesson.id)
    return {"success": True, "lesson_id": str(lesson.id)}