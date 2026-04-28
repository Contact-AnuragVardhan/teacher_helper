import re

_DEVANAGARI_DIGIT_MAP = str.maketrans(
    {
        "०": "0",
        "१": "1",
        "२": "2",
        "३": "3",
        "४": "4",
        "५": "5",
        "६": "6",
        "७": "7",
        "८": "8",
        "९": "9",
    }
)

_CHOICE_ALIASES = {
    "हाँ": "yes",
    "हां": "yes",
    "हा": "yes",
    "haan": "yes",
    "han": "yes",
    "ha": "yes",
    "yes": "yes",
    "y": "yes",
    "जी हाँ": "yes",
    "जी हां": "yes",
    "नहीं": "no",
    "नही": "no",
    "ना": "no",
    "nahin": "no",
    "nahi": "no",
    "no": "no",
    "n": "no",
}


def clean_text(value: str | None) -> str:
    return (value or "").strip()


def normalize_digits(value: str | None) -> str:
    return clean_text(value).translate(_DEVANAGARI_DIGIT_MAP)


def normalize_choice(value: str | None) -> str:
    cleaned = re.sub(r"\s+", " ", normalize_digits(value)).strip().casefold()
    return _CHOICE_ALIASES.get(cleaned, cleaned)


def normalize_grade(value: str | None) -> str:
    """Convert inputs like 'कक्षा 6', 'कक्षा ६', 'class 6', or 'Grade 6' to '6'."""
    cleaned = re.sub(r"\s+", " ", normalize_digits(value)).strip()
    if not cleaned:
        return ""

    match = re.search(r"\b(\d{1,2})\b", cleaned)
    if match:
        return match.group(1)

    return cleaned


def parse_duration_minutes(value: str | int | None) -> int | None:
    """Return minutes from inputs like 45, '45', '45 मिनट', or '४५ min'."""
    if isinstance(value, int):
        return value if value > 0 else None

    cleaned = normalize_digits(str(value) if value is not None else "")
    match = re.search(r"\d+", cleaned)
    if not match:
        return None

    minutes = int(match.group(0))
    return minutes if minutes > 0 else None


def is_blank(value: str | None) -> bool:
    return clean_text(value) == ""
