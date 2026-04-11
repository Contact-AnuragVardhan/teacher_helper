import re


_SUBJECT_ALIASES = {
    "math": "Mathematics",
    "maths": "Mathematics",
    "mathematics": "Mathematics",
    "social science": "Social Science",
    "social studies": "Social Science",
    "history": "Social Science",
    "geography": "Social Science",
    "economics": "Social Science",
    "civics": "Social Science",
    "political science": "Social Science",
    "political science civics": "Social Science",
    "political science (civics)": "Social Science",
}


def _normalize_key(value: str | None) -> str:
    cleaned = re.sub(r"\s+", " ", (value or "").strip())
    cleaned = re.sub(r"[\-_]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.casefold()



def normalize_subject(value: str | None) -> str:
    cleaned = re.sub(r"\s+", " ", (value or "").strip())
    if not cleaned:
        return ""

    canonical = _SUBJECT_ALIASES.get(_normalize_key(cleaned))
    if canonical:
        return canonical

    return cleaned
