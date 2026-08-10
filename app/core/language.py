from __future__ import annotations

import re

DEFAULT_LANGUAGE = "English"
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


def generation_language_instruction(
    value: str | None,
    *,
    preserve_source_text: bool = False,
) -> str:
    """Return the shared LLM output-language rule for Teacher Helper.

    ``preserve_source_text`` is used by PDF-backed generation, where exact
    textbook titles, formulas, names, or quoted source terms may legitimately
    remain in the book's original script even when the teacher's generated
    explanation is in another profile language.
    """
    key = language_key(value)
    if key == "hinglish":
        if preserve_source_text:
            return (
                "Write all newly generated explanations, bullets, and teaching guidance in simple Hinglish using Roman script only. "
                "Do not use Devanagari for newly generated prose. Use natural teacher-friendly Indian classroom wording with a light Hindi-English mix. "
                "Exact textbook titles, names, formulas, and quoted source terms may remain in their original script when referenced."
            )
        return (
            "Write all visible generated content in simple Hinglish using Roman script only. "
            "Do not use Devanagari. Use natural teacher-friendly Indian classroom wording with a light Hindi-English mix. "
            "Keep labels short and WhatsApp-friendly."
        )
    if key == "hindi":
        if preserve_source_text:
            return (
                "Write all newly generated explanations, bullets, labels, and section headings in simple Hindi using Devanagari script. "
                "Do not write Roman Hindi or Hinglish for newly generated prose. "
                "Exact textbook titles, names, formulas, and quoted source terms may remain exactly as supplied when referenced."
            )
        return (
            "Write all visible generated lesson content in simple Hindi using Devanagari script only. "
            "Do not write Roman Hindi or Hinglish. Translate section headings, labels, bullets, teaching tips, prompts, and the subject metadata value into Hindi/Devanagari. "
            "Keep any URLs unchanged."
        )
    if preserve_source_text:
        return (
            "Write all newly generated explanations, bullets, labels, and section headings in clear, simple English. "
            "Exact textbook titles, names, formulas, and quoted source terms may remain exactly as supplied when referenced."
        )
    return "Write all visible generated content in clear, simple English."

