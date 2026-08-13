from __future__ import annotations

import re

from app.core.language import language_key


def infer_toc_kind(
    *,
    structure_type: str | None,
    chapter_title: str | None = None,
    unit_title: str | None = None,
    section_title: str | None = None,
    lesson_title: str | None = None,
) -> str:
    """Return the teacher-facing TOC kind without promoting every row to Chapter.

    The pdf-to-embeddings schema keeps a generic parent row in
    ``embeddings_book_chapters`` even when the source TOC calls that row a lesson,
    poem, section, unit, or topic. ``structure_type`` is therefore the first
    authority for terminology. Field fallbacks are used only for older rows that
    do not have ``structure_type`` populated.
    """

    raw = re.sub(r"[^a-z0-9]+", " ", (structure_type or "").casefold()).strip()

    # Poems in school TOCs are commonly numbered as lessons even though the
    # structure_type may literally be "poem"/"poetry".
    if any(token in raw for token in ("poem", "poetry", "verse")):
        return "lesson"
    if "prose" in raw:
        return "chapter"
    if "lesson" in raw:
        return "lesson"
    if "chapter" in raw:
        return "chapter"
    if "section" in raw:
        return "section"
    if "unit" in raw:
        return "unit"
    if "topic" in raw:
        return "topic"

    # Backward-compatible inference for rows created before structure_type was
    # consistently populated. Prefer the most specific explicitly named field.
    if lesson_title:
        return "lesson"
    # If an older row has both chapter_title and section_title but no
    # structure_type, do not guess that the generic parent row is a Chapter.
    # The client's rule is stricter: only say Chapter when the TOC evidence is
    # unambiguous. In ambiguous legacy rows, retain the more specific field name.
    if section_title:
        return "section"
    if unit_title and not chapter_title:
        return "unit"
    if chapter_title:
        return "chapter"
    return "lesson"


def toc_label(kind: str | None, language: str | None = "English") -> str:
    resolved_kind = (kind or "lesson").casefold()
    lang = language_key(language or "English")

    if lang == "hindi":
        return {
            "chapter": "अध्याय",
            "lesson": "पाठ",
            "section": "खंड",
            "unit": "इकाई",
            "topic": "विषय",
        }.get(resolved_kind, "पाठ")

    # Hinglish intentionally uses the same concise Roman-script structural labels
    # as English so they remain aligned with the source TOC terminology.
    return {
        "chapter": "Chapter",
        "lesson": "Lesson",
        "section": "Section",
        "unit": "Unit",
        "topic": "Topic",
    }.get(resolved_kind, "Lesson")
