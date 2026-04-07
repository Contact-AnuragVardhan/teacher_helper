from dataclasses import dataclass
import re

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

    def generate(
        self,
        *,
        teacher: TeacherProfile,
        topic: str,
        duration_minutes: int,
        grade: str | None = None,
        subject: str | None = None,
    ) -> LessonGenerationResult:
        effective_grade = (grade or teacher.default_grade).strip()
        effective_subject = (subject or teacher.default_subject).strip()

        log_event(
            logger,
            "lesson_generation_started",
            teacher_id=teacher.id,
            topic=topic,
            duration_minutes=duration_minutes,
            preferred_language=teacher.preferred_language,
            grade=effective_grade,
            subject=effective_subject,
        )
        retrieved_chunks = self.retrieval_service.retrieve(
            grade=effective_grade,
            subject=effective_subject,
            topic=topic,
        )
        snippet_texts = [item.as_prompt_snippet() for item in retrieved_chunks]
        inspectable_rows = [item.as_inspectable_row() for item in retrieved_chunks]

        prompt = self.prompt_builder.build(
            PromptBuilderInput(
                grade=effective_grade,
                subject=effective_subject,
                preferred_language=teacher.preferred_language,
                topic=topic,
                duration_minutes=duration_minutes,
                retrieved_snippets=snippet_texts,
                matched_syllabus_rows=inspectable_rows,
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

        lesson_text = self._finalize_lesson_text(lesson_text, inspectable_rows)

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

    def _finalize_lesson_text(self, lesson_text: str, rows: list[dict]) -> str:
        text = (lesson_text or "").replace("\r\n", "\n").strip()
        if not text:
            return text

        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"\n+Matched syllabus row\s*\d*:.*$", "", text, flags=re.IGNORECASE | re.DOTALL)

        heading_labels = {
            "lesson title": "Lesson Title",
            "objective": "Objective",
            "opening": "Opening",
            "main teaching": "Main Teaching",
            "activity": "Activity",
            "q&a": "Q&A",
            "closing": "Closing",
            "source": "Source",
        }

        cleaned_lines: list[str] = []
        skip_generated_source_block = False
        skip_noise_block = False

        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                if cleaned_lines and cleaned_lines[-1] != "":
                    cleaned_lines.append("")
                continue

            heading_key = self._extract_heading_key(stripped)
            if heading_key:
                skip_noise_block = False
                if heading_key == "source":
                    skip_generated_source_block = True
                    continue

                skip_generated_source_block = False
                cleaned_lines.append(f"{heading_labels[heading_key]}:")
                continue

            if skip_generated_source_block:
                continue

            if skip_noise_block:
                continue

            normalized = self._normalize_inline_markdown(stripped)
            lowered = normalized.casefold()

            if any(
                lowered.startswith(prefix)
                for prefix in (
                    "grade:",
                    "subject:",
                    "book url:",
                    "topic summary:",
                    "keywords:",
                    "lesson goal:",
                    "matched ncert entry",
                    "useful chapter context:",
                    "teaching focus:",
                    "time:",
                    "expected responses:",
                    "board work",
                    "recitation focus",
                    "follow-up",
                    "homework",
                )
            ):
                if lowered.startswith(("expected responses:", "board work", "recitation focus")):
                    skip_noise_block = True
                continue

            cleaned_lines.append(normalized)

        text = "\n".join(self._squash_blank_lines(cleaned_lines)).strip()
        source_block = self._build_source_block(rows)
        if source_block:
            text = f"{text}\n\n{source_block}".strip()
        return re.sub(r"\n{3,}", "\n\n", text)

    def _extract_heading_key(self, line: str) -> str | None:
        normalized = self._normalize_inline_markdown(line)
        normalized = normalized.rstrip(":").strip()
        key = normalized.casefold()
        if key in {"lesson title", "objective", "opening", "main teaching", "activity", "q&a", "closing", "source"}:
            return key
        return None

    def _normalize_inline_markdown(self, text: str) -> str:
        value = text.strip()
        value = re.sub(r"^#{1,6}\s*", "", value)
        value = re.sub(r"^\*\*(.*?)\*\*$", r"\1", value).strip()
        value = re.sub(r"^__(.*?)__$", r"\1", value).strip()
        value = re.sub(r"^`(.*?)`$", r"\1", value).strip()
        return value

    def _squash_blank_lines(self, lines: list[str]) -> list[str]:
        output: list[str] = []
        for line in lines:
            if line == "":
                if output and output[-1] != "":
                    output.append("")
                continue
            output.append(line)
        while output and output[-1] == "":
            output.pop()
        return output

    def _build_source_block(self, rows: list[dict]) -> str:
        if not rows:
            return ""
        row = rows[0]
        lines = ["Source:", "NCERT"]
        book = row.get("book")
        chapter = row.get("topic_name") or row.get("chapter") or row.get("unit_name")
        if book:
            lines.append(f"Book: {book}")
        if chapter:
            lines.append(f"Chapter: {chapter}")
        return "\n".join(lines)
