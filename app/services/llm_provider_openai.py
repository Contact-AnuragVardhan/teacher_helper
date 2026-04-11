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

        needs_structure_retry = not self._is_response_well_structured(content)
        needs_quality_retry = self._looks_generic(content, prompt)

        if needs_structure_retry or needs_quality_retry:
            log_event(
                logger,
                "openai_revision_retry",
                model=self.model,
                needs_structure_retry=needs_structure_retry,
                needs_quality_retry=needs_quality_retry,
            )
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
                            "Revise your previous answer for Lesson Planning. "
                            "Keep the same seven lesson sections and no extra commentary. "
                            "Also keep the top summary block exactly like this before Lesson Title:\n"
                            "Lesson Planning\n"
                            f"Topic - {prompt.metadata.get('topic', '')}\n"
                            f"Grade/Class - {prompt.metadata.get('grade', '')}\n"
                            f"Subject - {prompt.metadata.get('subject', '')}\n"
                            f"Duration - {prompt.metadata.get('duration_minutes', '')} min\n\n"
                            "You MUST include timings exactly at the start of Opening, Main Teaching, Activity, Q&A, and Closing. "
                            "Use this exact timing distribution:\n"
                            f"{timing_hint}\n\n"
                            "Make the lesson topic-specific and directly usable. "
                            "Do not write vague lines such as 'Introduce the topic', 'Explain the concept', 'Use examples', "
                            "'Give students an activity', or 'Review the key learning'. "
                            "Instead, write the actual teaching content, actual examples, actual activity steps, and actual questions "
                            "for the requested topic. "
                            "Objective must be short separate lines. "
                            "Main Teaching must be numbered points. "
                            "Q&A must be exactly 4 numbered questions. "
                            "Do not add markdown headings, Source, or any extra sections."
                        ),
                    },
                ],
                temperature=0.0,
            )
            if revised:
                content = revised

        if not self._is_response_well_structured(content):
            log_event(logger, "openai_response_invalid_structure", model=self.model, content_preview=content[:500])
            raise RuntimeError("LLM response did not include the required lesson planning structure.")

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

    def _is_response_well_structured(self, text: str) -> bool:
        normalized = text.replace("\r\n", "\n").strip()
        if not normalized:
            return False

        return (
                self._has_top_summary_block(normalized)
                and self._has_required_sections(normalized)
                and self._has_required_timings(normalized)
                and self._has_numbered_questions(normalized)
        )

    def _has_top_summary_block(self, text: str) -> bool:
        normalized = text.replace("\r\n", "\n")

        first_section_match = re.search(
            r"(?im)^\s*(?:#+\s*)?(?:\*\*|__)?\s*"
            r"(Lesson Title|Objective|Opening|Main Teaching|Activity|Q\s*&\s*A|Closing)"
            r"\s*:?\s*(?:\*\*|__)?\s*$",
            normalized,
        )
        summary_block = normalized[: first_section_match.start()] if first_section_match else normalized

        checks = [
            r"(?im)^\s*Lesson Planning\s*:?\s*$",
            r"(?im)^\s*Topic\s*[-:]\s*.+$",
            r"(?im)^\s*Grade/Class\s*[-:]\s*.+$",
            r"(?im)^\s*Subject\s*[-:]\s*.+$",
            r"(?im)^\s*Duration\s*[-:]\s*.+$",
        ]
        return all(re.search(pattern, summary_block) for pattern in checks)

    def _has_required_sections(self, text: str) -> bool:
        required_sections = [
            "Lesson Title",
            "Objective",
            "Opening",
            "Main Teaching",
            "Activity",
            "Q&A",
            "Closing",
        ]
        normalized = text.replace("\r\n", "\n")

        for section in required_sections:
            label = r"Q\s*&\s*A" if section == "Q&A" else re.escape(section)
            pattern = (
                rf"(?im)^\s*(?:#+\s*)?(?:\*\*|__)?\s*{label}\s*:?\s*(?:\*\*|__)?\s*$"
            )
            if not re.search(pattern, normalized):
                return False

        return True

    def _has_required_timings(self, text: str) -> bool:
        required_sections = ["Opening", "Main Teaching", "Activity", "Q&A", "Closing"]
        normalized = text.replace("\r\n", "\n")

        timing_hits = 0
        for section in required_sections:
            label = r"Q\s*&\s*A" if section == "Q&A" else re.escape(section)
            pattern = (
                rf"(?ims)^\s*(?:#+\s*)?(?:\*\*|__)?\s*{label}\s*:?\s*(?:\*\*|__)?\s*$"
                rf"(?:\n\s*)*"
                rf"\(?\s*\d+(?:\s*[–-]\s*\d+)?\s*min\s*\)?"
            )
            if re.search(pattern, normalized):
                timing_hits += 1

        return timing_hits == len(required_sections)

    def _has_numbered_questions(self, text: str) -> bool:
        qa_block = self._extract_section_block(text, "Q&A", "Closing")
        if not qa_block:
            return False

        question_lines = re.findall(
            r"(?im)^\s*(?:\d+\s*[\.\):-]|\(\d+\)|\d+\s+-)\s+.+$",
            qa_block,
        )

        if len(question_lines) >= 4:
            return True

        fallback_question_lines = [
            line.strip()
            for line in qa_block.splitlines()
            if line.strip() and line.strip().endswith("?")
        ]
        return len(fallback_question_lines) >= 4

    def _extract_section_block(self, text: str, start_section: str, end_section: str | None = None) -> str:
        normalized = text.replace("\r\n", "\n")

        start_label = r"Q\s*&\s*A" if start_section == "Q&A" else re.escape(start_section)

        if end_section:
            end_label = r"Q\s*&\s*A" if end_section == "Q&A" else re.escape(end_section)
            pattern = (
                rf"(?ims)^\s*(?:#+\s*)?(?:\*\*|__)?\s*{start_label}\s*:?\s*(?:\*\*|__)?\s*$"
                rf"(.*?)"
                rf"(?=^\s*(?:#+\s*)?(?:\*\*|__)?\s*{end_label}\s*:?\s*(?:\*\*|__)?\s*$)"
            )
        else:
            pattern = (
                rf"(?ims)^\s*(?:#+\s*)?(?:\*\*|__)?\s*{start_label}\s*:?\s*(?:\*\*|__)?\s*$"
                rf"(.*)$"
            )

        match = re.search(pattern, normalized, flags=re.MULTILINE)
        return match.group(1).strip() if match else ""

    def _looks_generic(self, text: str, prompt: PromptBundle) -> bool:
        normalized = text.casefold()
        generic_phrases = [
            "introduce the topic in simple",
            "explain the most important concept",
            "use one or two relevant examples",
            "give students a short individual, pair, or group activity",
            "what is the main idea of today",
            "what is one important point you learned",
            "review the key learning in short points",
            "ask students to share one takeaway",
        ]
        if any(phrase in normalized for phrase in generic_phrases):
            return True

        topic = str(prompt.metadata.get("topic", "")).strip().casefold()
        topic_tokens = re.findall(r"[a-z0-9]+", topic)
        meaningful_tokens = [token for token in topic_tokens if len(token) > 3]
        if not meaningful_tokens:
            return False

        hits = sum(1 for token in meaningful_tokens if token in normalized)
        return hits == 0
