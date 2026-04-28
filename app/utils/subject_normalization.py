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
