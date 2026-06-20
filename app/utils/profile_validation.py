from app.core.config import Settings
from app.utils.subject_normalization import normalize_subject, subject_allowed_key


def _grade_keys(grade: str | None) -> set[str]:
    raw = (grade or "").strip().casefold().replace(" ", "")
    digits = "".join(ch for ch in raw if ch.isdigit())
    keys = {raw} if raw else set()
    if digits:
        keys.update({digits, f"class{digits}", f"class-{digits}", f"grade{digits}", f"grade-{digits}"})
    return keys


def validate_profile_grade(grade: str, settings: Settings) -> str | None:
    if not settings.profile_allowed_grades_casefold:
        return None
    if grade.strip().casefold() in settings.profile_allowed_grades_casefold:
        return None
    return f"Grade must be one of: {', '.join(settings.profile_allowed_grades_list)}."


def validate_profile_subject(subject: str, grade: str, settings: Settings) -> str | None:
    normalized_subject = normalize_subject(subject)
    if not normalized_subject.strip():
        return "Subject cannot be blank."

    allowed_by_grade = settings.profile_allowed_subjects_by_grade_map
    if not allowed_by_grade:
        return None

    grade_keys = _grade_keys(grade)
    allowed_subjects: list[str] = []
    for configured_grade, configured_subjects in allowed_by_grade.items():
        if _grade_keys(configured_grade) & grade_keys:
            allowed_subjects = configured_subjects
            break

    # If env has no rule for this grade, do not block the teacher flow.
    if not allowed_subjects:
        return None

    normalized_key = subject_allowed_key(normalized_subject)
    allowed_keys = {subject_allowed_key(item) for item in allowed_subjects}
    if normalized_key in allowed_keys:
        return None

    return f"Subject for Grade {grade} must be one of: {', '.join(allowed_subjects)}."
