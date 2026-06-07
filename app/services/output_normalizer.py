"""Normalize LLM lesson output for display, save, and WhatsApp.

Adapted from the plan_b lesson pipeline so Teacher Helper applies the same
cleanup after OpenAI returns a lesson plan.
"""

from __future__ import annotations

import re

MAX_LINE_LENGTH = 100

# Keep existing section/bullet-like lines intact while splitting long prose.
_SECTION_OR_BULLET_PREFIX = re.compile(r"^[\U0001F300-\U0001FAFF]|^[⭐✅⏱]|^[#*•\-]|^\s*\|")
_SUB_BULLET_LABEL = re.compile(r"^(Example|Prompt|Step|Expected|Note|Sub-?step)\s*:", re.IGNORECASE)
_INDENT = "  "


def remove_html(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    for entity, char in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">")):
        text = text.replace(entity, char)
    return text


def remove_markdown_tables(text: str) -> str:
    if not text:
        return text
    lines = text.split("\n")
    out: list[str] = []
    in_table = False
    for line in lines:
        stripped = line.strip()
        is_table_line = "|" in stripped and (
            stripped.startswith("|")
            or stripped.endswith("|")
            or re.match(r"^[\|\s\-:]+$", stripped)
        )
        if is_table_line:
            in_table = True
            continue
        if in_table and not stripped:
            in_table = False
        if not is_table_line:
            in_table = False
            out.append(line)
    return "\n".join(out)


def remove_latex_wrappers(text: str) -> str:
    """Remove LaTeX display/inline delimiters while keeping inner content."""
    if not text:
        return text
    text = re.sub(r"\\\[\s*(.*?)\s*\\\]", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"\\\(\s*(.*?)\s*\\\)", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"\$\$(.*?)\$\$", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"\$(.*?)\$", r"\1", text)
    return text


def convert_fractions(text: str) -> str:
    """Convert LaTeX \\frac{a}{b} to a/b."""
    if not text:
        return text

    def _frac_repl(match: re.Match) -> str:
        return f"{match.group(1).strip()}/{match.group(2).strip()}"

    pattern = r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}"
    previous = None
    while previous != text:
        previous = text
        text = re.sub(pattern, _frac_repl, text)
    return text


def remove_latex_commands(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"\\[a-zA-Z]+\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\[a-zA-Z]+", "", text)
    return text


def _split_sentence_line(line: str) -> list[str]:
    if len(line) <= MAX_LINE_LENGTH:
        return [line]
    parts = re.split(r"(?<=[.!?।])\s+", line.strip())
    if len(parts) <= 1:
        words = line.split()
        rows: list[str] = []
        current: list[str] = []
        length = 0
        for word in words:
            if length + len(word) + 1 > MAX_LINE_LENGTH and current:
                rows.append(" ".join(current))
                current = [word]
                length = len(word)
            else:
                current.append(word)
                length += len(word) + 1
        if current:
            rows.append(" ".join(current))
        return rows

    rows: list[str] = []
    buffer: list[str] = []
    buffer_len = 0
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if buffer_len + len(part) + 1 > MAX_LINE_LENGTH and buffer:
            rows.append(" ".join(buffer))
            buffer = [part]
            buffer_len = len(part)
        else:
            buffer.append(part)
            buffer_len += len(part) + 1
    if buffer:
        rows.append(" ".join(buffer))
    return rows


def split_long_paragraphs(text: str) -> str:
    if not text:
        return text
    out_lines: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if (
            not stripped
            or _SECTION_OR_BULLET_PREFIX.match(stripped)
            or stripped.startswith("*")
            or stripped.startswith("-")
            or stripped.startswith("•")
            or re.match(r"^\d+[.)]\s", stripped)
            or line.startswith(_INDENT)
        ):
            out_lines.append(line)
            continue
        if len(stripped) > MAX_LINE_LENGTH or (len(stripped) > 60 and ". " in stripped):
            out_lines.extend(_split_sentence_line(stripped))
        elif ". " in stripped and len(stripped) > 40:
            parts = re.split(r"(?<=[.!?।])\s+", stripped)
            out_lines.extend(parts if len(parts) > 1 else [stripped])
        else:
            out_lines.append(line)
    return "\n".join(out_lines)


def normalize_lesson_indentation(text: str) -> str:
    if not text:
        return text
    out: list[str] = []
    for line in text.split("\n"):
        if not line.strip():
            out.append(line)
            continue
        stripped = line.strip()
        if line.startswith(_INDENT):
            inner = line[len(_INDENT) :].lstrip()
            # Avoid the bad '* - text' output when the LLM already supplied a bullet.
            if inner.startswith(("*", "-", "•")):
                out.append(f"{_INDENT}{inner}")
            else:
                out.append(f"{_INDENT}* {inner}")
            continue
        if stripped.startswith("*"):
            label_part = stripped[1:].lstrip()
            if _SUB_BULLET_LABEL.match(label_part):
                out.append(f"{_INDENT}{stripped}")
            else:
                out.append(stripped)
            continue
        if _SUB_BULLET_LABEL.match(stripped):
            out.append(f"{_INDENT}* {stripped}")
            continue
        out.append(line)
    return "\n".join(out)


def normalize_whitespace(text: str) -> str:
    """Collapse excessive blank lines and trim line endings."""
    if not text:
        return text
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_lesson_output(text: str) -> str:
    """Full normalization pipeline for generated lesson output."""
    if not text:
        return ""
    text = remove_html(text)
    text = remove_markdown_tables(text)
    text = remove_latex_wrappers(text)
    text = convert_fractions(text)
    text = remove_latex_commands(text)
    text = split_long_paragraphs(text)
    text = normalize_lesson_indentation(text)
    text = normalize_whitespace(text)
    return text
