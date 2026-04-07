import re

from openai import OpenAI

from app.core.config import Settings
from app.core.logging import get_logger, log_event
from app.services.lesson_generation_provider import LessonGenerationProvider, PromptBundle

logger = get_logger(__name__)


class OpenAILessonGenerationProvider(LessonGenerationProvider):
    provider_name = "openai"

    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")
        client_kwargs: dict[str, str] = {"api_key": settings.openai_api_key}
        if settings.openai_base_url:
            client_kwargs["base_url"] = settings.openai_base_url
        self.client = OpenAI(**client_kwargs)
        self.model = settings.openai_model
        log_event(logger, "openai_provider_initialized", model=self.model, has_base_url=bool(settings.openai_base_url))

    def generate(self, prompt: PromptBundle) -> str:
        log_event(logger, "openai_request_started", model=self.model)

        content = self._create_completion(
            messages=[
                {"role": "system", "content": prompt.system_prompt},
                {"role": "user", "content": prompt.user_prompt},
            ],
            temperature=0.2,
        )

        if not content:
            log_event(logger, "openai_response_empty", model=self.model)
            raise RuntimeError("LLM response was empty.")

        if not self._has_required_timings(content):
            log_event(logger, "openai_timing_retry", model=self.model)
            timing_map = prompt.metadata.get("timing_map", {})
            timing_hint = (
                f"Opening -> ({timing_map.get('opening', 'required')})\n"
                f"Main Teaching -> ({timing_map.get('main_teaching', 'required')})\n"
                f"Activity -> ({timing_map.get('activity', 'required')})\n"
                f"Q&A -> ({timing_map.get('qa', 'required')})\n"
                f"Closing -> ({timing_map.get('closing', 'required')})"
            )
            revised = self._create_completion(
                messages=[
                    {"role": "system", "content": prompt.system_prompt},
                    {"role": "user", "content": prompt.user_prompt},
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            "Revise your previous answer. Keep the same seven sections and no extra commentary. "
                            "You MUST include timings exactly at the start of Opening, Main Teaching, Activity, Q&A, and Closing. "
                            "Use this exact timing distribution:\n"
                            f"{timing_hint}\n\n"
                            "Do not add markdown headings, Source, or any extra sections."
                        ),
                    },
                ],
                temperature=0.0,
            )
            if revised:
                content = revised

        if not self._has_required_timings(content):
            log_event(logger, "openai_response_missing_timings", model=self.model)
            raise RuntimeError("LLM response did not include required timings.")

        log_event(logger, "openai_request_completed", model=self.model)
        return content.strip()

    def _create_completion(self, *, messages: list[dict[str, str]], temperature: float) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            messages=messages,
        )
        content = response.choices[0].message.content if response.choices else None
        return (content or "").strip()

    def _has_required_timings(self, text: str) -> bool:
        required_sections = ["Opening", "Main Teaching", "Activity", "Q&A", "Closing"]
        normalized = text.replace("\r\n", "\n")
        for section in required_sections:
            pattern = (
                rf"(?im)^\s*(?:#+\s*)?\**\s*{re.escape(section)}\s*\**\s*$"
                rf"\n\s*\(?\s*\d+(?:\s*[–-]\s*\d+)?\s*min\s*\)?"
            )
            if not re.search(pattern, normalized):
                return False
        return True
