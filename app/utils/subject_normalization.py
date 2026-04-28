import re

CANONICAL_SUBJECTS = (
    "Mathematics",
    "Science",
    "English",
    "Hindi",
    "Social Science",
)

_SUBJECT_ALIASES = {
    "math": "Mathematics",
    "maths": "Mathematics",
    "mathematics": "Mathematics",
    "गणित": "Mathematics",
    "मैथ": "Mathematics",

    "science": "Science",
    "विज्ञान": "Science",
    "साइंस": "Science",

    "english": "English",
    "अंग्रेजी": "English",
    "इंग्लिश": "English",

    "hindi": "Hindi",
    "हिंदी": "Hindi",
    "हिन्दी": "Hindi",

    "social science": "Social Science",
    "social studies": "Social Science",
    "history": "Social Science",
    "geography": "Social Science",
    "economics": "Social Science",
    "civics": "Social Science",
    "social": "Social Science",
    "सामाजिक विज्ञान": "Social Science",
    "इतिहास": "Social Science",
    "भूगोल": "Social Science",
    "नागरिक शास्त्र": "Social Science",

    # Existing aliases kept for backward compatibility.
    "political science": "Social Science",
    "political science civics": "Social Science",
    "political science (civics)": "Social Science",
}


def _normalize_key(value: str | None) -> str:
    cleaned = re.sub(r"\s+", " ", (value or "").strip())
    cleaned = re.sub(r"[\-_]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.casefold()


def clean_subject(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def resolve_subject_alias(value: str | None) -> str | None:
    cleaned = clean_subject(value)
    if not cleaned:
        return ""
    return _SUBJECT_ALIASES.get(_normalize_key(cleaned))


def normalize_subject(value: str | None) -> str:
    cleaned = clean_subject(value)
    if not cleaned:
        return ""

    canonical = resolve_subject_alias(cleaned)
    if canonical:
        return canonical

    return cleaned


def is_canonical_subject(value: str | None) -> bool:
    key = _normalize_key(value)
    return any(key == item.casefold() for item in CANONICAL_SUBJECTS)

_SUBJECT_DISPLAY_HINDI = {
    "Mathematics": "गणित",
    "Science": "विज्ञान",
    "English": "अंग्रेज़ी",
    "Hindi": "हिंदी",
    "Social Science": "सामाजिक विज्ञान",
}


def subject_display_name(value: str | None, *, language: str | None = None) -> str:
    """Return a display-friendly subject name for the selected UI/lesson language.

    Storage and validation continue to use canonical English subject names.
    Hindi lesson output should show the subject in Devanagari, so canonical
    values like ``Social Science`` are rendered as ``सामाजिक विज्ञान``.
    """
    canonical = normalize_subject(value)
    if not canonical:
        return ""

    if (language or "").strip().casefold() == "hindi":
        return _SUBJECT_DISPLAY_HINDI.get(canonical, canonical)

    return canonical
