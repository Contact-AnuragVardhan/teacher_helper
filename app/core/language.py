from __future__ import annotations

import re

DEFAULT_LANGUAGE = "Hindi"
SUPPORTED_LANGUAGE_NAMES = ("Hindi", "English", "Hinglish")

_LANGUAGE_ALIASES = {
    "hindi": "Hindi",
    "हिंदी": "Hindi",
    "हिन्दी": "Hindi",
    "हिन्दि": "Hindi",
    "hin": "Hindi",
    "english": "English",
    "eng": "English",
    "en": "English",
    "hinglish": "Hinglish",
    "hindi english": "Hinglish",
    "hindi-english": "Hinglish",
    "roman hindi": "Hinglish",
}


def _language_lookup_key(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", (value or "").strip()).casefold()
    cleaned = cleaned.replace("_", "-")
    return cleaned


def normalize_language(value: str | None, *, default: str | None = DEFAULT_LANGUAGE) -> str | None:
    """Return the app's canonical language name, or default when no supported match exists."""
    if value is None or not str(value).strip():
        return default

    key = _language_lookup_key(str(value))
    if key in _LANGUAGE_ALIASES:
        return _LANGUAGE_ALIASES[key]

    compact_key = key.replace("-", " ")
    if compact_key in _LANGUAGE_ALIASES:
        return _LANGUAGE_ALIASES[compact_key]

    return default


def language_key(value: str | None) -> str:
    return (normalize_language(value) or DEFAULT_LANGUAGE).casefold()
