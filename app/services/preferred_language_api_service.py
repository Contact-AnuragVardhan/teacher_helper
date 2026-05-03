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
    """Read and write a user's language preference in Jalta Sitara Hotline.

    Teacher Helper keeps its own profile language, but Jalta Sitara Hotline is
    the shared preference store. We read it when resolving language, and we also
    update it when a teacher creates or edits the profile language in Teacher
    Helper.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def fetch_preferred_language(self, phone_number: str) -> PreferredLanguageResult | None:
        if not self._is_enabled():
            log_event(logger, "preferred_language_api_disabled")
            return None

        base_url = self._base_url()
        if not base_url:
            log_event(logger, "preferred_language_api_missing_base_url")
            return None

        phone_candidates = self._phone_candidates(phone_number)
        if not phone_candidates:
            log_event(logger, "preferred_language_api_missing_phone", phone_number=phone_number)
            return None

        for candidate in phone_candidates:
            for endpoint_name, url, params in self._get_endpoints(base_url, candidate):
                result = self._fetch_from_endpoint(endpoint_name, url, params)
                if result:
                    return result

        log_event(logger, "preferred_language_api_no_match", phone_number=phone_number)
        return None

    def update_preferred_language(self, phone_number: str, preferred_language: str) -> PreferredLanguageResult | None:
        """Save the selected profile language into Jalta Sitara Hotline.

        Tries the new POST API first, then falls back to the path-style PUT API.
        Phone number normalization happens in the Hotline app, but we still send
        a stable +digits value when possible.
        """
        if not self._is_enabled():
            log_event(logger, "preferred_language_update_api_disabled")
            return None

        base_url = self._base_url()
        if not base_url:
            log_event(logger, "preferred_language_update_missing_base_url")
            return None

        normalized_language = normalize_language((preferred_language or "").strip(), default=None)
        if not normalized_language or normalized_language.casefold() not in self.settings.supported_languages_casefold:
            log_event(
                logger,
                "preferred_language_update_skipped_invalid_language",
                phone_number=phone_number,
                preferred_language=preferred_language,
            )
            return None

        phone_candidates = self._phone_candidates(phone_number)
        if not phone_candidates:
            log_event(logger, "preferred_language_update_missing_phone", phone_number=phone_number)
            return None

        canonical_phone = self._canonical_plus_phone(phone_candidates[0])
        # Hotline POST accepts only phone_number and preferred_language.
        # Do not send Teacher Helper's internal whatsapp_number field here.
        payload = {
            "phone_number": canonical_phone,
            "preferred_language": normalized_language,
        }

        endpoints = [
            (
                "language_preference_post",
                "post",
                f"{base_url}/api/preferences/language",
                payload,
            ),
            (
                "user_preferred_language_put",
                "put",
                f"{base_url}/api/users/{quote(canonical_phone, safe='')}/preferred-language",
                {"preferred_language": normalized_language},
            ),
        ]

        for endpoint_name, method, url, json_payload in endpoints:
            result = self._write_to_endpoint(endpoint_name, method, url, json_payload)
            if result:
                return result

        log_event(
            logger,
            "preferred_language_update_failed_all_endpoints",
            phone_number=canonical_phone,
            preferred_language=normalized_language,
        )
        return None

    def sync_preferred_language_if_needed(
        self,
        phone_number: str | None = None,
        selected_language: str | None = None,
        *,
        whatsapp_number: str | None = None,
        preferred_language: str | None = None,
    ) -> PreferredLanguageResult | None:
        """Best-effort Hotline sync when its saved value differs.

        Use `phone_number` for new call sites. `whatsapp_number` is accepted only
        as an internal backward-compatible alias so older code does not crash.
        Outbound Hotline API JSON uses exactly the schema required by Hotline:
        `phone_number` and `preferred_language`; it never sends `whatsapp_number`.
        """
        phone = (phone_number or whatsapp_number or "").strip()
        normalized_language = normalize_language((selected_language or preferred_language or "").strip(), default=None)
        if not phone or not normalized_language:
            return None

        try:
            current = self.fetch_preferred_language(phone)
            if current and current.preferred_language.casefold() == normalized_language.casefold():
                log_event(
                    logger,
                    "preferred_language_update_not_needed",
                    phone_number=phone,
                    preferred_language=normalized_language,
                )
                return current

            return self.update_preferred_language(phone, normalized_language)
        except Exception as exc:  # pragma: no cover - defensive; Hotline must not break profile flow.
            log_event(
                logger,
                "preferred_language_sync_ignored",
                phone_number=phone,
                preferred_language=normalized_language,
                error=str(exc),
            )
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
        except Exception as exc:
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

    def _write_to_endpoint(
        self,
        endpoint_name: str,
        method: str,
        url: str,
        json_payload: dict[str, str],
    ) -> PreferredLanguageResult | None:
        try:
            request = httpx.post if method == "post" else httpx.put
            response = request(
                url,
                json=json_payload,
                timeout=self.settings.jalta_sitara_hotline_language_api_timeout_seconds,
            )
            if response.status_code == 404:
                log_event(logger, "preferred_language_update_not_found", endpoint=endpoint_name)
                return None
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            log_event(
                logger,
                "preferred_language_update_error",
                endpoint=endpoint_name,
                error=str(exc),
            )
            return None

        result = self._parse_payload(payload)
        if result:
            log_event(
                logger,
                "preferred_language_update_success",
                endpoint=endpoint_name,
                phone_number=result.phone_number,
                preferred_language=result.preferred_language,
                source=result.source,
            )
        else:
            log_event(logger, "preferred_language_update_invalid_payload", endpoint=endpoint_name)
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

    def _get_endpoints(self, base_url: str, phone_number: str) -> list[tuple[str, str, dict[str, str] | None]]:
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

    def _canonical_plus_phone(self, phone_number: str) -> str:
        digits = "".join(ch for ch in (phone_number or "") if ch.isdigit())
        return f"+{digits}" if digits else (phone_number or "").strip()

    def _base_url(self) -> str:
        return (self.settings.jalta_sitara_hotline_base_url or "").rstrip("/")

    def _is_enabled(self) -> bool:
        return bool(self.settings.jalta_sitara_hotline_language_api_enabled)
