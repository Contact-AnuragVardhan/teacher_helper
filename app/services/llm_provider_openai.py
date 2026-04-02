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
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": prompt.system_prompt},
                {"role": "user", "content": prompt.user_prompt},
            ],
        )
        content = response.choices[0].message.content if response.choices else None
        if not content:
            log_event(logger, "openai_response_empty", model=self.model)
            raise RuntimeError("LLM response was empty.")
        log_event(logger, "openai_request_completed", model=self.model)
        return content.strip()
