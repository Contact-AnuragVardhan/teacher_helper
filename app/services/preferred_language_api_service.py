from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings
from app.core.language import normalize_language
from app.core.logging import get_logger, log_event

logger = get_logger(__name__)


@dataclass(frozen=True)
class PreferredLanguageResult:
    phone_number: str
    preferred_language: str
    source: str | None = None
    supported_languages: list[str] = field(default_factory=list)


class PreferredLanguageApiService:
    """Fetch a user's language preference from the Jalta Sitara Hotline service.

    Teacher Helper still keeps its local profile/default-language behavior. This
    service is used after that local resolution so the Jalta Sitara Hotline preference
    can override and sync the Teacher Helper profile when available.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def fetch_preferred_language(self, phone_number: str) -> PreferredLanguageResult | None:
        if not self.settings.jalta_sitara_hotline_language_api_enabled:
            log_event(logger, "preferred_language_api_disabled")
            return None

        base_url = (self.settings.jalta_sitara_hotline_base_url or "").rstrip("/")
        if not base_url:
            log_event(logger, "preferred_language_api_missing_base_url")
            return None

        phone_candidates = self._phone_candidates(phone_number)
        if not phone_candidates:
            log_event(logger, "preferred_language_api_missing_phone", phone_number=phone_number)
            return None

        for candidate in phone_candidates:
            for endpoint_name, url, params in self._endpoints(base_url, candidate):
                result = self._fetch_from_endpoint(endpoint_name, url, params)
                if result:
                    return result

        log_event(logger, "preferred_language_api_no_match", phone_number=phone_number)
        return None

    def _fetch_from_endpoint(
        self,
        endpoint_name: str,
        url: str,
        params: dict[str, str] | None,
    ) -> PreferredLanguageResult | None:
        try:
            response = httpx.get(
                url,
                params=params,
                timeout=self.settings.jalta_sitara_hotline_language_api_timeout_seconds,
            )
            if response.status_code == 404:
                log_event(logger, "preferred_language_api_not_found", endpoint=endpoint_name)
                return None
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            log_event(
                logger,
                "preferred_language_api_error",
                endpoint=endpoint_name,
                error=str(exc),
            )
            return None

        result = self._parse_payload(payload)
        if result:
            log_event(
                logger,
                "preferred_language_api_success",
                endpoint=endpoint_name,
                phone_number=result.phone_number,
                preferred_language=result.preferred_language,
                source=result.source,
            )
        else:
            log_event(logger, "preferred_language_api_invalid_payload", endpoint=endpoint_name)
        return result

    def _parse_payload(self, payload: Any) -> PreferredLanguageResult | None:
        if not isinstance(payload, dict):
            return None

        raw_language = (payload.get("preferred_language") or "").strip()
        preferred_language = normalize_language(raw_language, default=None)
        if not preferred_language:
            return None

        if preferred_language.casefold() not in self.settings.supported_languages_casefold:
            log_event(
                logger,
                "preferred_language_api_unsupported_local_language",
                preferred_language=preferred_language,
            )
            return None

        supported_languages = self._normalize_supported_languages(payload.get("supported_languages"))
        if supported_languages and preferred_language.casefold() not in {
            item.casefold() for item in supported_languages
        }:
            log_event(
                logger,
                "preferred_language_api_language_not_in_remote_supported_list",
                preferred_language=preferred_language,
                remote_supported_languages=supported_languages,
            )
            return None

        return PreferredLanguageResult(
            phone_number=str(payload.get("phone_number") or "").strip(),
            preferred_language=preferred_language,
            source=str(payload.get("source") or "").strip() or None,
            supported_languages=supported_languages,
        )

    def _normalize_supported_languages(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []

        normalized: list[str] = []
        for item in value:
            language = normalize_language(str(item), default=None)
            if language and language.casefold() in self.settings.supported_languages_casefold:
                normalized.append(language)
        return normalized

    def _endpoints(self, base_url: str, phone_number: str) -> list[tuple[str, str, dict[str, str] | None]]:
        encoded_phone = quote(phone_number, safe="")
        return [
            (
                "user_preferred_language",
                f"{base_url}/api/users/{encoded_phone}/preferred-language",
                None,
            ),
            (
                "language_preference_query",
                f"{base_url}/api/preferences/language",
                {"phone_number": phone_number},
            ),
        ]

    def _phone_candidates(self, phone_number: str) -> list[str]:
        raw = (phone_number or "").strip()
        digits = "".join(ch for ch in raw if ch.isdigit())
        candidates: list[str] = []
        if digits:
            candidates.append(digits)
            candidates.append(f"+{digits}")
        elif raw:
            candidates.append(raw)

        unique_candidates: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate not in seen:
                unique_candidates.append(candidate)
                seen.add(candidate)
        return unique_candidates
