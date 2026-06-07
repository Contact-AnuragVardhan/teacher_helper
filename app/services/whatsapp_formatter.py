"""WhatsApp presentation layer for generated lesson output.

Adapted from the plan_b lesson pipeline. This keeps LLM output short, readable,
and compatible with WhatsApp formatting conventions.
"""

from __future__ import annotations

import re

from app.services.output_normalizer import normalize_lesson_output

SECTION_MARKERS = [
    (r"(?i)^\s*(summary|lesson overview)\s*:?\s*$", "📚 Lesson Overview"),
    (r"(?i)^\s*learning goal(s)?\s*:?\s*$", "🎯 Learning Goal"),
    (r"(?i)^\s*learning objectives?\s*:?\s*$", "🎯 Learning Goal"),
    (r"(?i)^\s*objectives?\s*:?\s*$", "🎯 Learning Goal"),
    (r"(?i)^\s*vocabulary\s*:?\s*$", "📖 Vocabulary"),
    (r"(?i)^\s*materials?( needed)?(\s*\([^)]*\))?\s*:?\s*$", "🧰 Materials Needed"),
    (r"(?i)^\s*teacher (explanation|notes?)(\s*\([^)]*\))?\s*:?\s*$", "👩‍🏫 Teacher Explanation"),
    (r"(?i)^\s*book connection\s*:?\s*$", "📖 Book Connection"),
    (r"(?i)^\s*student activit(y|ies)(\s*\([^)]*\))?\s*:?\s*$", "👥 Student Activity"),
    (r"(?i)^\s*activit(y|ies)(\s*\([^)]*\))?\s*:?\s*$", "👥 Student Activity"),
    (r"(?i)^\s*(check (for )?understanding|assessment)(\s*\([^)]*\))?\s*:?\s*$", "✅ Check Understanding"),
    (r"(?i)^\s*homework(\s*\([^)]*\))?\s*:?\s*$", "🏠 Homework"),
    (r"(?i)^\s*teacher quick view\s*:?\s*$", "⭐ Teacher Quick View"),
]

TEACHER_NOTE_PATTERN = re.compile(r"(?i)^\s*(teacher note|note for teacher|tip)\s*:\s*(.+)$")
_EMOJI_HEADER = re.compile(r"^([\U0001F300-\U0001FAFF⭐✅⏱][^\n]*?)(\s*\(\s*\d+\s*min[^)]*\))?\s*$")
_HEADER_EMOJIS = "📚🎯🧰👩👥✅🏠⭐📖⏱"


def _bold_header(line: str) -> str:
    clean = line.strip().rstrip(":")
    if clean.startswith("*") and clean.endswith("*"):
        return clean
    return f"*{clean}*"


def normalize_bullets(text: str) -> str:
    """Normalize bullet characters to * while preserving indentation."""
    lines: list[str] = []
    for line in text.split("\n"):
        lead = len(line) - len(line.lstrip(" "))
        indent = line[:lead]
        stripped = line.strip()
        bullet_match = re.match(r"^[-*•]\s+(.+)$", stripped)
        if bullet_match:
            lines.append(f"{indent}* {bullet_match.group(1)}")
            continue
        numbered_match = re.match(r"^(\d+)[.)]\s+(.+)$", stripped)
        if numbered_match:
            lines.append(f"{indent}{numbered_match.group(1)}. {numbered_match.group(2)}")
            continue
        lines.append(line)
    return "\n".join(lines)


def ensure_section_spacing(text: str) -> str:
    """Keep major sections visually separated."""
    lines = text.split("\n")
    out: list[str] = []
    prev_was_header = False
    for line in lines:
        stripped = line.strip()
        is_header = bool(
            stripped
            and (
                _EMOJI_HEADER.match(stripped)
                or (stripped.startswith("*") and any(emoji in stripped for emoji in _HEADER_EMOJIS))
            )
        )
        if is_header and out and out[-1].strip() and not prev_was_header:
            out.append("")
        out.append(line)
        prev_was_header = is_header
    result = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", result).strip()


def format_whatsapp_lesson(text: str) -> str:
    """Format normalized lesson for WhatsApp delivery."""
    text = normalize_lesson_output(text)
    lines = text.split("\n")
    formatted: list[str] = []

    for line in lines:
        if not line.strip():
            formatted.append("")
            continue

        stripped = line.strip()
        teacher_note = TEACHER_NOTE_PATTERN.match(stripped)
        if teacher_note:
            formatted.append(f"_Teacher note: {teacher_note.group(2).strip()}_")
            continue

        if _EMOJI_HEADER.match(stripped) and any(emoji in stripped for emoji in _HEADER_EMOJIS):
            formatted.append(_bold_header(stripped))
            continue

        for pattern, marker in SECTION_MARKERS:
            if re.match(pattern, stripped):
                timing = re.search(r"\(\s*\d+\s*min[^)]*\)", line, re.IGNORECASE)
                marked = f"{marker}{timing.group(0)}" if timing else marker
                formatted.append(_bold_header(marked))
                break
        else:
            if re.match(r"^[A-Z][^.\n]{0,60}:$", stripped) or re.match(r"^#{1,3}\s+.+$", stripped):
                header = stripped.lstrip("#").strip().rstrip(":")
                formatted.append(_bold_header(header))
            elif stripped.startswith(("*", "-")) or line.startswith("  "):
                formatted.append(normalize_bullets(line))
            else:
                formatted.append(line)

    result = "\n".join(formatted)
    result = normalize_bullets(result)
    result = ensure_section_spacing(result)
    return result.strip()
