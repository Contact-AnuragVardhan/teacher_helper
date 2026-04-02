from app.core.config import Settings


def validate_profile_grade(grade: str, settings: Settings) -> str | None:
    if not settings.profile_allowed_grades_casefold:
        return None
    if grade.strip().casefold() in settings.profile_allowed_grades_casefold:
        return None
    return f"Grade must be one of: {', '.join(settings.profile_allowed_grades_list)}."


def validate_profile_subject(subject: str, grade: str, settings: Settings) -> str | None:
    subject_clean = subject.strip()
    grade_clean = grade.strip()

    allowed_map = settings.profile_allowed_subjects_by_grade_map
    allowed_map_casefold = settings.profile_allowed_subjects_by_grade_casefold

    if not allowed_map_casefold:
        return None

    allowed_subjects_casefold = allowed_map_casefold.get(grade_clean.casefold())
    if not allowed_subjects_casefold:
        return f"No allowed subjects are configured for grade {grade_clean}."

    if subject_clean.casefold() in allowed_subjects_casefold:
        return None

    display_subjects = allowed_map.get(grade_clean, [])
    return f"For grade {grade_clean}, subject must be one of: {', '.join(display_subjects)}."