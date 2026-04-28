from __future__ import annotations

import json
import re

from app.core.config import Settings
from app.core.logging import get_logger, log_event
from app.utils.subject_normalization import (
    CANONICAL_SUBJECTS,
    clean_subject,
    is_canonical_subject,
    normalize_subject,
    resolve_subject_alias,
)

logger = get_logger(__name__)


class SubjectResolver:
    """Resolve teacher-entered subject names before validation/storage.

    The first pass is deterministic and handles Hindi/Devanagari aliases.  The
    LLM fallback is intentionally small and separate from lesson generation; it
    only returns a canonical subject name for typo/variant inputs.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def resolve(self, value: str | None, *, language: str | None = None) -> str:
        cleaned = clean_subject(value)
        if not cleaned:
            return ""

        alias = resolve_subject_alias(cleaned)
        if alias:
            return alias

        if is_canonical_subject(cleaned):
            return normalize_subject(cleaned)

        resolved = self._resolve_with_llm(cleaned, language=language)
        if resolved:
            return resolved

        return normalize_subject(cleaned)

    def _resolve_with_llm(self, value: str, *, language: str | None = None) -> str | None:
        if self.settings.llm_provider == "deterministic" or not self.settings.openai_api_key:
            log_event(
                logger,
                "subject_llm_resolver_skipped",
                reason="deterministic_or_missing_openai_key",
                subject_input=value,
            )
            return None

        try:
            from openai import OpenAI

            client_kwargs: dict[str, str] = {"api_key": self.settings.openai_api_key}
            if self.settings.openai_base_url:
                client_kwargs["base_url"] = self.settings.openai_base_url
            client = OpenAI(**client_kwargs)

            allowed = ", ".join(CANONICAL_SUBJECTS)
            prompt = (
                "Normalize the user's school subject into one canonical English subject.\n"
                f"Allowed canonical subjects: {allowed}.\n"
                "The input may be English, Hindi in Devanagari, Hinglish, or misspelled.\n"
                "Map History, Geography, Civics, Economics, and Social Studies to Social Science.\n"
                "If the input cannot reasonably be mapped, return null.\n\n"
                "Return ONLY compact JSON in this exact shape: {\"subject\": \"Science\"} or {\"subject\": null}.\n\n"
                f"Preferred language context: {language or 'unknown'}\n"
                f"User input: {value}"
            )

            response = client.chat.completions.create(
                model=self.settings.openai_model,
                temperature=0,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a strict subject-normalization helper. Return JSON only.",
                    },
                    {"role": "user", "content": prompt},
                ],
            )
            content = (response.choices[0].message.content if response.choices else "") or ""
            resolved = self._extract_subject_from_llm_response(content)
            if resolved:
                log_event(
                    logger,
                    "subject_llm_resolver_completed",
                    subject_input=value,
                    normalized_subject=resolved,
                )
            else:
                log_event(
                    logger,
                    "subject_llm_resolver_no_match",
                    subject_input=value,
                    response_preview=content[:200],
                )
            return resolved
        except Exception as exc:  # noqa: BLE001 - keep user flow alive if LLM normalization fails.
            log_event(
                logger,
                "subject_llm_resolver_failed",
                subject_input=value,
                error=str(exc),
            )
            return None

    def _extract_subject_from_llm_response(self, content: str) -> str | None:
        text = (content or "").strip()
        if not text:
            return None

        try:
            parsed = json.loads(text)
            subject = parsed.get("subject") if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if not match:
                subject = text
            else:
                try:
                    parsed = json.loads(match.group(0))
                    subject = parsed.get("subject") if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    subject = text

        if subject is None:
            return None

        normalized = normalize_subject(str(subject))
        if is_canonical_subject(normalized):
            return normalized

        return None
