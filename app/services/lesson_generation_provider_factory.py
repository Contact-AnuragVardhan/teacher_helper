from app.core.config import Settings
from app.services.lesson_generation_provider import LessonGenerationProvider
from app.services.llm_provider_openai import OpenAILessonGenerationProvider
from app.services.model_profiles import resolve_model_profile






def build_lesson_generation_provider(settings: Settings) -> LessonGenerationProvider:
    
    if settings.llm_provider == "deterministic":
        from app.services.deterministic_provider import DeterministicLessonGenerationProvider
        return DeterministicLessonGenerationProvider(settings)

    profile = resolve_model_profile(settings.openai_model)

    if profile.provider == "openai":
        return OpenAILessonGenerationProvider(settings)

    if profile.provider == "google":
        raise NotImplementedError(
            f"Model '{settings.openai_model}' maps to Google, but Google provider is not implemented yet."
        )

    raise RuntimeError(
        f"Unsupported provider '{profile.provider}' for model '{settings.openai_model}'."
    )