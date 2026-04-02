from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.logging import get_logger, log_event
from app.models.teacher_profile import TeacherProfile
from app.services.deterministic_provider import DeterministicTemplateProvider
from app.services.lesson_generation_provider import LessonGenerationProvider
from app.services.llm_provider_openai import OpenAILessonGenerationProvider
from app.services.ncert_retrieval_service import NcertRetrievalService
from app.services.prompt_builder import PromptBuilder, PromptBuilderInput

logger = get_logger(__name__)


@dataclass(slots=True)
class LessonGenerationResult:
    lesson_text: str
    provider_used: str
    retrieved_sources: list[str]
    matched_syllabus_rows: list[dict]


class LessonGeneratorService:
    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        retrieval_service: NcertRetrievalService | None = None,
        prompt_builder: PromptBuilder | None = None,
        deterministic_provider: LessonGenerationProvider | None = None,
        openai_provider: LessonGenerationProvider | None = None,
    ):
        self.db = db
        self.settings = settings or get_settings()
        self.retrieval_service = retrieval_service or NcertRetrievalService(db)
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.deterministic_provider = deterministic_provider or DeterministicTemplateProvider()
        self.openai_provider = openai_provider

    def generate(self, *, teacher: TeacherProfile, topic: str, duration_minutes: int) -> LessonGenerationResult:
        log_event(
            logger,
            "lesson_generation_started",
            teacher_id=teacher.id,
            topic=topic,
            duration_minutes=duration_minutes,
            preferred_language=teacher.preferred_language,
        )
        retrieved_chunks = self.retrieval_service.retrieve(
            grade=teacher.default_grade,
            subject=teacher.default_subject,
            topic=topic,
        )
        snippet_texts = [item.as_prompt_snippet() for item in retrieved_chunks]
        inspectable_rows = [item.as_inspectable_row() for item in retrieved_chunks]

        prompt = self.prompt_builder.build(
            PromptBuilderInput(
                grade=teacher.default_grade,
                subject=teacher.default_subject,
                preferred_language=teacher.preferred_language,
                topic=topic,
                duration_minutes=duration_minutes,
                retrieved_snippets=snippet_texts,
            )
        )

        try:
            provider = self._primary_provider()
            log_event(logger, "lesson_generation_provider_selected", provider=provider.provider_name)
            lesson_text = provider.generate(prompt)
            provider_used = provider.provider_name
        except Exception as exc:
            requested_provider = getattr(locals().get("provider"), "provider_name", self.settings.llm_provider)
            log_event(
                logger,
                "lesson_generation_fallback",
                requested_provider=requested_provider,
                error=str(exc),
            )
            lesson_text = self.deterministic_provider.generate(prompt)
            provider_used = self.deterministic_provider.provider_name

        log_event(
            logger,
            "lesson_generation_complete",
            provider_used=provider_used,
            retrieval_count=len(retrieved_chunks),
            retrieved_sources=[item.source_title for item in retrieved_chunks],
        )
        return LessonGenerationResult(
            lesson_text=lesson_text,
            provider_used=provider_used,
            retrieved_sources=[item.source_title for item in retrieved_chunks],
            matched_syllabus_rows=inspectable_rows,
        )

    def _primary_provider(self) -> LessonGenerationProvider:
        if self.settings.llm_provider == "openai":
            if self.openai_provider is not None:
                log_event(logger, "lesson_generation_provider_reused", provider="openai")
                return self.openai_provider
            log_event(logger, "lesson_generation_provider_initialized", provider="openai")
            return OpenAILessonGenerationProvider(self.settings)
        log_event(logger, "lesson_generation_provider_initialized", provider=self.deterministic_provider.provider_name)
        return self.deterministic_provider