from openai import OpenAI

from app.core.config import Settings
from app.services.lesson_generation_provider import LessonGenerationProvider, PromptBundle


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

    def generate(self, prompt: PromptBundle) -> str:
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
            raise RuntimeError("LLM response was empty.")
        return content.strip()
