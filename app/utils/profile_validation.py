from app.core.config import Settings


def validate_profile_grade(grade: str, settings: Settings) -> str | None:
    if not settings.profile_allowed_grades_casefold:
        return None
    if grade.strip().casefold() in settings.profile_allowed_grades_casefold:
        return None
    return f"Grade must be one of: {', '.join(settings.profile_allowed_grades_list)}."



def validate_profile_subject(subject: str, grade: str, settings: Settings) -> str | None:
    del grade, settings

    if subject.strip():
        return None

    return "Subject cannot be blank."
