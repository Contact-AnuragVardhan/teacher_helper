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

        needs_structure_retry = not self._is_response_well_structured(content, prompt)
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
                f"1. Opening -> ({timing_map.get('opening', 'required')} min)\n"
                f"2. Concept Teaching -> ({timing_map.get('concept_teaching', 'required')} min)\n"
                f"3. Guided Practice -> ({timing_map.get('guided_practice', 'required')} min)\n"
                f"4. Concept Reinforcement -> ({timing_map.get('concept_reinforcement', 'required')} min)\n"
                f"5. Independent Practice -> ({timing_map.get('independent_practice', 'required')} min)\n"
                f"6. Assessment / Check -> ({timing_map.get('assessment', 'required')} min)\n"
                f"7. Closure -> ({timing_map.get('closure', 'required')} min)"
            )
            has_ncert_match = bool(prompt.metadata.get("has_ncert_match"))
            language_instruction = self._revision_language_instruction(
                str(prompt.metadata.get("preferred_language", "English"))
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
                            "Keep it smartphone-friendly with short bullets and clear blank lines between groups. "
                            "This is a plan, not a long explanation. "
                            "Use this exact summary block before Lesson Title:\n"
                            "Lesson Planning\n"
                            f"Topic: {prompt.metadata.get('topic', '')}\n"
                            f"Grade/Class: {prompt.metadata.get('grade', '')}\n"
                            f"Subject: {prompt.metadata.get('subject', '')}\n"
                            f"Duration: {prompt.metadata.get('duration_minutes', '')} minutes\n\n"
                            "Use these section headings in order: Lesson Title, Objectives, 1. Opening, 2. Concept Teaching, "
                            "3. Guided Practice, 4. Concept Reinforcement, 5. Independent Practice, 6. Assessment / Check, 7. Closure, Teaching Tips. "
                            "Use Learn More only when there is no NCERT match. "
                            "Do not add Source because the app adds it separately. "
                            "Keep the timing in the same heading line for sections 1 to 7. "
                            "Use this exact timing distribution:\n"
                            f"{timing_hint}\n\n"
                            "Make the lesson topic-specific and directly usable. "
                            "Avoid generic filler like 'Introduce the topic' or 'Use examples'. "
                            "Write the actual concepts, actual teacher moves, actual student tasks, and actual quick checks. "
                            "Objectives must be short bullet points. "
                            "Teaching Tips must be short bullet points. "
                            "No markdown tables. No long paragraphs. "
                            f"{language_instruction} "
                            + (
                                "Do not include Learn More or any YouTube link because NCERT was matched."
                                if has_ncert_match
                                else "Include Learn More with exactly one relevant YouTube link."
                            )
                        ),
                    },
                ],
                temperature=0.0,
            )
            if revised:
                content = revised

        if not self._is_response_well_structured(content, prompt):
            log_event(logger, "openai_response_invalid_structure", model=self.model, content_preview=content[:500])
            raise RuntimeError("LLM response did not include the required lesson planning structure.")

        log_event(logger, "openai_request_completed", model=self.model)
        return content.strip()

    def _revision_language_instruction(self, preferred_language: str) -> str:
        language = preferred_language.strip().casefold()
        if language == "hindi":
            return (
                "Keep structural headings and metadata labels in English, but write the lesson title, "
                "objectives, bullets, teaching tips, and teaching content in Hindi using Devanagari script only. "
                "Do not use Roman Hindi or Hinglish."
            )
        if language == "hinglish":
            return (
                "Keep section headings in English and write the lesson body in simple Hinglish using Roman script only. "
                "Do not use Devanagari."
            )
        return "Write the lesson in clear, simple English."

    def _create_completion(self, *, messages: list[dict[str, str]], temperature: float) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            messages=messages,
        )
        content = response.choices[0].message.content if response.choices else None
        return (content or "").strip()

    def _is_response_well_structured(self, text: str, prompt: PromptBundle) -> bool:
        normalized = text.replace("\r\n", "\n").strip()
        if not normalized:
            return False

        if not self._has_top_summary_block(normalized):
            return False

        if not self._has_required_sections(normalized):
            return False

        if not self._has_required_timings(normalized):
            return False

        if not self._has_list_like_content(normalized):
            return False

        if not self._has_learn_more_requirement(normalized, prompt):
            return False

        return True

    def _has_top_summary_block(self, text: str) -> bool:
        english_summary_checks = [
            r"(?im)^\s*Lesson Planning\s*:?[ \t]*$",
            r"(?im)^\s*Topic\s*[-:]\s*.+$",
            r"(?im)^\s*Grade/Class\s*[-:]\s*.+$",
            r"(?im)^\s*Subject\s*[-:]\s*.+$",
            r"(?im)^\s*Duration\s*[-:]\s*.+$",
        ]
        hindi_summary_checks = [
            r"(?im)^\s*पाठ योजना\s*:?[ \t]*$",
            r"(?im)^\s*(?:टॉपिक|विषय)\s*[-:]\s*.+$",
            r"(?im)^\s*(?:ग्रेड/कक्षा|कक्षा)\s*[-:]\s*.+$",
            r"(?im)^\s*(?:विषय|Subject)\s*[-:]\s*.+$",
            r"(?im)^\s*(?:अवधि|Duration)\s*[-:]\s*.+$",
        ]
        return all(re.search(pattern, text) for pattern in english_summary_checks) or all(
            re.search(pattern, text) for pattern in hindi_summary_checks
        )

    def _has_required_sections(self, text: str) -> bool:
        new_sections = [
            r"Lesson Title",
            r"Objectives?",
            r"1\.\s*Opening",
            r"2\.\s*Concept Teaching",
            r"3\.\s*Guided Practice",
            r"4\.\s*Concept Reinforcement",
            r"5\.\s*Independent Practice",
            r"6\.\s*Assessment\s*/\s*Check",
            r"7\.\s*Closure",
            r"Teaching Tips",
        ]
        legacy_sections = [
            r"Lesson Title",
            r"Objective",
            r"Opening",
            r"Main Teaching",
            r"Activity",
            r"Q\s*&\s*A",
            r"Closing",
        ]
        hindi_sections = [
            r"पाठ शीर्षक",
            r"उद्देश्य",
            r"1\.\s*(?:शुरुआत|प्रारंभ)",
            r"2\.\s*(?:अवधारणा शिक्षण|मुख्य शिक्षण)",
            r"3\.\s*निर्देशित अभ्यास",
            r"4\.\s*अवधारणा सुदृढ़ीकरण",
            r"5\.\s*स्वतंत्र अभ्यास",
            r"6\.\s*(?:मूल्यांकन\s*/\s*जाँच|मूल्यांकन|जाँच)",
            r"7\.\s*समापन",
            r"शिक्षण सुझाव",
        ]

        if self._has_section_set(text, new_sections):
            return True
        if self._has_section_set(text, legacy_sections):
            return True
        return self._has_section_set(text, hindi_sections)

    def _has_section_set(self, text: str, sections: list[str]) -> bool:
        for section in sections:
            pattern = rf"(?im)^\s*(?:#+\s*)?(?:\*\*|__)?\s*{section}\s*(?:\([^\n]+\))?\s*:?[ \t]*(?:\*\*|__)?$"
            if not re.search(pattern, text):
                return False
        return True

    def _has_required_timings(self, text: str) -> bool:
        timing_line_count = len(
            re.findall(
                r"(?im)^\s*(?:[1-7]\.)?\s*[^\n()]+\(\s*\d+(?:\s*[–-]\s*\d+)?\s*min\s*\)\s*:?[ \t]*$",
                text,
            )
        )
        if timing_line_count >= 5:
            return True

        standalone_timing_count = len(
            re.findall(r"(?im)^\s*\(?\s*\d+(?:\s*[–-]\s*\d+)?\s*min\s*\)?\s*$", text)
        )
        return standalone_timing_count >= 5

    def _has_list_like_content(self, text: str) -> bool:
        bullet_lines = re.findall(r"(?im)^\s*[-•*]\s+.+$", text)
        numbered_lines = re.findall(r"(?im)^\s*\d+\s*[\.)-]\s+.+$", text)
        return len(bullet_lines) + len(numbered_lines) >= 8

    def _has_learn_more_requirement(self, text: str, prompt: PromptBundle) -> bool:
        has_ncert_match = bool(prompt.metadata.get("has_ncert_match"))
        has_learn_more = bool(re.search(r"(?im)^\s*(?:Learn More|और सीखें|अधिक सीखें)\s*:?[ \t]*$", text))
        has_youtube = "youtube.com" in text.casefold() or "youtu.be" in text.casefold()

        if has_ncert_match:
            return not has_youtube
        return has_learn_more and has_youtube

    def _looks_generic(self, text: str, prompt: PromptBundle) -> bool:
        normalized = text.casefold()
        generic_phrases = [
            "introduce the topic",
            "explain the concept",
            "use examples",
            "review the lesson",
            "ask students to share one takeaway",
            "give students a short activity",
            "link the topic to prior knowledge",
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
