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
from app.utils.subject_normalization import normalize_subject
from urllib.parse import unquote

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
        effective_subject = normalize_subject(subject or teacher.default_subject)

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
        # Client requirement: do not send stored NCERT chunks to the LLM.
        # The prompt now asks the LLM to identify an NCERT reference from its own knowledge if possible.
        retrieved_chunks = []
        snippet_texts = []
        inspectable_rows = []
        log_event(
            logger,
            "lesson_generation_ncert_context_skipped",
            topic=topic,
            grade=effective_grade,
            subject=effective_subject,
            reason="ncert_data_not_sent_to_llm",
        )

        log_event(
            logger,
            "lesson_generation_effective_inputs",
            topic=topic,
            requested_grade=grade,
            requested_subject=subject,
            teacher_default_grade=teacher.default_grade,
            teacher_default_subject=teacher.default_subject,
            effective_grade=effective_grade,
            effective_subject=effective_subject,
        )

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

        lesson_text = self._finalize_lesson_text(
            lesson_text,
            rows=inspectable_rows,
            topic=topic,
            grade=effective_grade,
            subject=effective_subject,
            duration_minutes=duration_minutes,
            preferred_language=teacher.preferred_language,
        )

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

    def _finalize_lesson_text(
        self,
        lesson_text: str,
        *,
        rows: list[dict],
        topic: str,
        grade: str,
        subject: str,
        duration_minutes: int,
        preferred_language: str,
    ) -> str:
        raw_text = (lesson_text or "").replace("\r\n", "\n").strip()
        if not raw_text:
            return raw_text

        raw_text = self._strip_preface_lines(raw_text)
        raw_text = re.sub(r"\n{3,}", "\n\n", raw_text)
        raw_text = re.sub(r"\n+Matched syllabus row\s*\d*:.*$", "", raw_text, flags=re.IGNORECASE | re.DOTALL)

        llm_source_block = self._extract_llm_source_block(raw_text)
        parsed_sections = self._parse_sections(raw_text)
        normalized_text = self._render_normalized_lesson(
            sections=parsed_sections,
            topic=topic,
            grade=grade,
            subject=subject,
            duration_minutes=duration_minutes,
            preferred_language=preferred_language,
            has_ncert_match=bool(llm_source_block),
            raw_text=raw_text,
        )

        if llm_source_block:
            normalized_text = f"{normalized_text}\n\n{llm_source_block}".strip()

        return re.sub(r"\n{3,}", "\n\n", normalized_text).strip()

    def _strip_preface_lines(self, text: str) -> str:
        cleaned_lines: list[str] = []
        started = False
        preface_patterns = (
            "here is your generated lesson plan",
            "here is the generated lesson plan",
            "generated lesson plan",
            "lesson plan:",
        )

        for line in text.splitlines():
            stripped = line.strip()
            lowered = stripped.casefold()
            if not started:
                if not stripped:
                    continue
                if lowered in {"lesson planning", "पाठ योजना"}:
                    started = True
                    cleaned_lines.append(stripped)
                    continue
                if lowered.startswith(preface_patterns):
                    continue
            cleaned_lines.append(line)

        return "\n".join(cleaned_lines).strip()

    def _parse_sections(self, text: str) -> dict[str, list[str]]:
        sections: dict[str, list[str]] = {}
        current_key: str | None = None
        skip_top_summary = False

        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                if current_key and sections.get(current_key) and sections[current_key][-1] != "":
                    sections[current_key].append("")
                continue

            lowered = stripped.casefold()
            if lowered in {"lesson planning", "पाठ योजना"}:
                skip_top_summary = True
                continue

            if skip_top_summary and self._is_top_summary_line(stripped):
                continue
            skip_top_summary = False

            section_key = self._extract_section_key(stripped)
            if section_key == "source":
                current_key = None
                continue
            if section_key:
                current_key = section_key
                sections.setdefault(current_key, [])
                continue

            if current_key is None:
                continue

            normalized = self._normalize_inline_markdown(stripped)
            if not normalized:
                continue
            sections[current_key].append(normalized)

        return sections

    def _render_normalized_lesson(
        self,
        *,
        sections: dict[str, list[str]],
        topic: str,
        grade: str,
        subject: str,
        duration_minutes: int,
        preferred_language: str,
        has_ncert_match: bool,
        raw_text: str,
    ) -> str:
        is_hindi = self._is_hindi_language(preferred_language)
        labels = self._labels_for_language(preferred_language)
        planning_block = self._build_planning_block(
            topic=topic,
            grade=grade,
            subject=subject,
            duration_minutes=duration_minutes,
            preferred_language=preferred_language,
        )

        timing_map = self._allocate_timings(duration_minutes)
        output: list[str] = [planning_block]

        title_lines = self._prepare_content_lines(
            sections.get("lesson_title", []),
            section_key="lesson_title",
            preferred_language=preferred_language,
        )
        if not title_lines:
            title_lines = [f"{topic.strip()} का सरल पाठ" if is_hindi else self._title_case(topic.strip())]
        output.extend(["", labels["lesson_title"]])
        output.extend(self._as_bullets(title_lines, force_bullet=True))

        objective_lines = self._prepare_content_lines(
            sections.get("objectives", []),
            section_key="objectives",
            preferred_language=preferred_language,
        )
        if not objective_lines:
            if is_hindi:
                objective_lines = [
                    f"{topic.strip()} की मुख्य बात समझना",
                    f"{topic.strip()} से जुड़े ज़रूरी बिंदु सरल शब्दों में बताना",
                    f"कक्षा चर्चा या अभ्यास में {topic.strip()} का उपयोग करना",
                ]
            else:
                objective_lines = [
                    f"Understand the main idea of {topic.strip()}",
                    f"Explain key points from {topic.strip()} in simple words",
                    f"Use the concept from {topic.strip()} in class discussion or practice",
                ]
        output.extend(["", labels["objectives"]])
        output.extend(self._as_bullets(objective_lines, force_bullet=True))

        ordered_sections = [
            ("opening", labels["opening"], timing_map["opening"]),
            ("concept_teaching", labels["concept_teaching"], timing_map["concept_teaching"]),
            ("guided_practice", labels["guided_practice"], timing_map["guided_practice"]),
            ("concept_reinforcement", labels["concept_reinforcement"], timing_map["concept_reinforcement"]),
            ("independent_practice", labels["independent_practice"], timing_map["independent_practice"]),
            ("assessment", labels["assessment"], timing_map["assessment"]),
            ("closure", labels["closure"], timing_map["closure"]),
        ]

        for key, label, minutes in ordered_sections:
            content_lines = self._prepare_content_lines(
                sections.get(key, []),
                section_key=key,
                preferred_language=preferred_language,
            )
            if not content_lines:
                content_lines = self._fallback_section_lines(key, topic, preferred_language=preferred_language)
            heading = f"{label} ({minutes} min)"
            output.extend(["", heading])
            output.extend(self._as_bullets(content_lines, force_bullet=True))

        teaching_tips = self._prepare_content_lines(
            sections.get("teaching_tips", []),
            section_key="teaching_tips",
            preferred_language=preferred_language,
        )
        if not teaching_tips:
            if is_hindi:
                teaching_tips = [
                    "हर व्याख्या छोटी रखें और समझ की जाँच करते रहें",
                    "लंबी थ्योरी के बजाय बोर्ड, गतिविधि या छोटा प्रदर्शन करें",
                    "इसे शिक्षण योजना मानें; ज़रूरत के अनुसार कक्षा में विस्तार करें",
                ]
            else:
                teaching_tips = [
                    "Keep each explanation short and check understanding often",
                    "Use board work, body movement, or a quick demo instead of long theory",
                    "Treat this as a teaching plan; expand verbally in class",
                ]
        output.extend(["", labels["teaching_tips"]])
        output.extend(self._as_bullets(teaching_tips, force_bullet=True))

        if not has_ncert_match:
            learn_more_lines = self._prepare_content_lines(
                sections.get("learn_more", []),
                section_key="learn_more",
                preferred_language=preferred_language,
            )
            youtube_url = self._find_youtube_url(learn_more_lines) or self._find_youtube_url([raw_text])
            if youtube_url:
                learn_more_lines = [youtube_url]
            elif learn_more_lines:
                learn_more_lines = self._as_plain_lines(learn_more_lines)
            else:
                learn_more_lines = [
                    f"https://www.youtube.com/results?search_query={self._youtube_query(topic, subject)}"
                ]
            output.extend(["", labels["learn_more"]])
            output.extend(self._as_bullets(learn_more_lines[:1], force_bullet=True))

        return "\n".join(output).strip()

    def _extract_section_key(self, line: str) -> str | None:
        normalized = self._normalize_inline_markdown(self._strip_leading_emoji(line)).rstrip(":").strip()
        key = re.sub(r"\s+", " ", normalized.casefold())
        key_without_parens = re.sub(r"\s*\([^)]*\)\s*$", "", key).strip()

        exact_mapping = {
            "lesson title": "lesson_title",
            "objective": "objectives",
            "objectives": "objectives",
            "opening": "opening",
            "1. opening": "opening",
            "concept teaching": "concept_teaching",
            "2. concept teaching": "concept_teaching",
            "main teaching": "concept_teaching",
            "guided practice": "guided_practice",
            "3. guided practice": "guided_practice",
            "activity": "guided_practice",
            "concept reinforcement": "concept_reinforcement",
            "4. concept reinforcement": "concept_reinforcement",
            "independent practice": "independent_practice",
            "5. independent practice": "independent_practice",
            "assessment / check": "assessment",
            "6. assessment / check": "assessment",
            "assessment": "assessment",
            "check": "assessment",
            "q&a": "assessment",
            "closure": "closure",
            "7. closure": "closure",
            "closing": "closure",
            "conclusion": "closure",
            "teaching tips": "teaching_tips",
            "teacher tip": "teaching_tips",
            "teacher tips": "teaching_tips",
            "learn more": "learn_more",
            "पाठ शीर्षक": "lesson_title",
            "शीर्षक": "lesson_title",
            "उद्देश्य": "objectives",
            "लक्ष्य": "objectives",
            "शुरुआत": "opening",
            "1. शुरुआत": "opening",
            "प्रारंभ": "opening",
            "1. प्रारंभ": "opening",
            "अवधारणा शिक्षण": "concept_teaching",
            "2. अवधारणा शिक्षण": "concept_teaching",
            "मुख्य शिक्षण": "concept_teaching",
            "2. मुख्य शिक्षण": "concept_teaching",
            "निर्देशित अभ्यास": "guided_practice",
            "3. निर्देशित अभ्यास": "guided_practice",
            "गतिविधि": "guided_practice",
            "3. गतिविधि": "guided_practice",
            "अवधारणा सुदृढ़ीकरण": "concept_reinforcement",
            "4. अवधारणा सुदृढ़ीकरण": "concept_reinforcement",
            "स्वतंत्र अभ्यास": "independent_practice",
            "5. स्वतंत्र अभ्यास": "independent_practice",
            "मूल्यांकन / जाँच": "assessment",
            "6. मूल्यांकन / जाँच": "assessment",
            "मूल्यांकन": "assessment",
            "जाँच": "assessment",
            "समापन": "closure",
            "7. समापन": "closure",
            "शिक्षण सुझाव": "teaching_tips",
            "शिक्षक सुझाव": "teaching_tips",
            "और सीखें": "learn_more",
            "अधिक सीखें": "learn_more",
            "स्रोत": "source",
            "source": "source",
        }

        for candidate in (key, key_without_parens):
            if candidate in exact_mapping:
                return exact_mapping[candidate]

        prefix_mapping = [
            ("lesson title", "lesson_title"),
            ("objectives", "objectives"),
            ("objective", "objectives"),
            ("1. opening", "opening"),
            ("opening", "opening"),
            ("2. concept teaching", "concept_teaching"),
            ("concept teaching", "concept_teaching"),
            ("main teaching", "concept_teaching"),
            ("3. guided practice", "guided_practice"),
            ("guided practice", "guided_practice"),
            ("activity", "guided_practice"),
            ("4. concept reinforcement", "concept_reinforcement"),
            ("concept reinforcement", "concept_reinforcement"),
            ("5. independent practice", "independent_practice"),
            ("independent practice", "independent_practice"),
            ("6. assessment / check", "assessment"),
            ("assessment / check", "assessment"),
            ("assessment", "assessment"),
            ("q&a", "assessment"),
            ("7. closure", "closure"),
            ("closure", "closure"),
            ("closing", "closure"),
            ("teaching tips", "teaching_tips"),
            ("teacher tips", "teaching_tips"),
            ("teacher tip", "teaching_tips"),
            ("learn more", "learn_more"),
            ("पाठ शीर्षक", "lesson_title"),
            ("शीर्षक", "lesson_title"),
            ("उद्देश्य", "objectives"),
            ("लक्ष्य", "objectives"),
            ("1. शुरुआत", "opening"),
            ("शुरुआत", "opening"),
            ("1. प्रारंभ", "opening"),
            ("प्रारंभ", "opening"),
            ("2. अवधारणा शिक्षण", "concept_teaching"),
            ("अवधारणा शिक्षण", "concept_teaching"),
            ("2. मुख्य शिक्षण", "concept_teaching"),
            ("मुख्य शिक्षण", "concept_teaching"),
            ("3. निर्देशित अभ्यास", "guided_practice"),
            ("निर्देशित अभ्यास", "guided_practice"),
            ("गतिविधि", "guided_practice"),
            ("4. अवधारणा सुदृढ़ीकरण", "concept_reinforcement"),
            ("अवधारणा सुदृढ़ीकरण", "concept_reinforcement"),
            ("5. स्वतंत्र अभ्यास", "independent_practice"),
            ("स्वतंत्र अभ्यास", "independent_practice"),
            ("6. मूल्यांकन / जाँच", "assessment"),
            ("मूल्यांकन / जाँच", "assessment"),
            ("मूल्यांकन", "assessment"),
            ("जाँच", "assessment"),
            ("7. समापन", "closure"),
            ("समापन", "closure"),
            ("शिक्षण सुझाव", "teaching_tips"),
            ("शिक्षक सुझाव", "teaching_tips"),
            ("और सीखें", "learn_more"),
            ("अधिक सीखें", "learn_more"),
            ("स्रोत", "source"),
            ("source", "source"),
        ]
        for candidate in (key, key_without_parens):
            for prefix, mapped in prefix_mapping:
                if candidate.startswith(prefix):
                    return mapped
        return None

    def _prepare_content_lines(self, lines: list[str], *, section_key: str, preferred_language: str = "English") -> list[str]:
        compacted = self._compact_label_value_lines(lines)
        cleaned: list[str] = []
        for line in compacted:
            value = self._strip_list_marker(self._strip_leading_emoji(self._normalize_inline_markdown(line))).strip()
            if not value:
                continue
            if value.casefold().startswith(
                (
                    "topic:",
                    "grade/class:",
                    "subject:",
                    "duration:",
                    "टॉपिक:",
                    "ग्रेड/कक्षा:",
                    "कक्षा:",
                    "विषय:",
                    "अवधि:",
                )
            ):
                continue
            if self._is_timing_line(value):
                continue
            value = self._normalize_house_style_line(
                value,
                section_key=section_key,
                preferred_language=preferred_language,
            )
            if not value:
                continue
            cleaned.append(value)
        limited = self._limit_lines(cleaned, section_key=section_key)
        return limited

    def _compact_label_value_lines(self, lines: list[str]) -> list[str]:
        output: list[str] = []
        i = 0
        while i < len(lines):
            current = lines[i].strip()
            if not current:
                i += 1
                continue
            if self._is_timing_line(current):
                output.append(current)
                i += 1
                continue

            if current.endswith(":") and i + 1 < len(lines):
                nxt = lines[i + 1].strip()
                if nxt and not self._looks_like_heading(nxt) and not self._is_timing_line(nxt) and not nxt.endswith(":"):
                    output.append(f"{current} {self._strip_list_marker(nxt)}")
                    i += 2
                    continue

            output.append(current)
            i += 1
        return output

    def _normalize_house_style_line(self, text: str, *, section_key: str, preferred_language: str = "English") -> str:
        value = re.sub(r"\s+", " ", text).strip()
        value = re.sub(r"^[\"'“”‘’]+|[\"'“”‘’]+$", "", value).strip()
        value = re.sub(r"\s*[–—]\s*", " - ", value)
        value = re.sub(r"\s*→\s*", ": ", value)
        value = re.sub(r"\s*:\s*", ": ", value)
        value = re.sub(r"\s*;\s*", "; ", value)

        if section_key != "learn_more" and value.casefold().startswith("here is your generated lesson plan"):
            return ""

        value = self._split_overstuffed_line(value, section_key=section_key)
        value = value.strip(" -")
        if not value:
            return ""

        if section_key == "lesson_title":
            return value if self._is_hindi_language(preferred_language) else self._title_case(value)

        if re.match(r"^[A-Za-z][A-Za-z /&-]{1,40}:\s", value):
            label, rest = value.split(":", 1)
            rest = self._trim_plan_length(rest.strip(), section_key=section_key)
            if not rest:
                return ""
            return self._localize_hindi_bullet_label(
                f"{self._title_case(label.strip())}: {self._sentence_case(rest)}",
                preferred_language,
            )

        trimmed = self._trim_plan_length(value, section_key=section_key)
        if section_key in {"objectives", "teaching_tips"}:
            return self._localize_hindi_bullet_label(
                self._sentence_case(trimmed, keep_short=True),
                preferred_language,
            )
        return self._localize_hindi_bullet_label(self._sentence_case(trimmed), preferred_language)

    def _split_overstuffed_line(self, value: str, *, section_key: str) -> str:
        if section_key in {"learn_more", "lesson_title"}:
            return value
        if len(value) <= 150:
            return value
        if ";" in value:
            return value.split(";", 1)[0].strip()
        if ": " in value:
            label, rest = value.split(": ", 1)
            first_sentence = re.split(r"(?<=[.!?])\s+", rest, maxsplit=1)[0].strip()
            return f"{label}: {first_sentence}".strip()
        return re.split(r"(?<=[.!?])\s+", value, maxsplit=1)[0].strip()

    def _trim_plan_length(self, value: str, *, section_key: str) -> str:
        value = value.strip()
        if section_key == "learn_more":
            return value

        max_len_by_section = {
            "lesson_title": 80,
            "objectives": 90,
            "opening": 110,
            "concept_teaching": 125,
            "guided_practice": 120,
            "concept_reinforcement": 115,
            "independent_practice": 105,
            "assessment": 90,
            "closure": 100,
            "teaching_tips": 90,
        }
        max_len = max_len_by_section.get(section_key, 110)
        if len(value) <= max_len:
            return value
        clipped = value[: max_len - 1].rstrip(" ,;:-")
        return clipped.strip()

    def _limit_lines(self, lines: list[str], *, section_key: str) -> list[str]:
        max_lines_by_section = {
            "lesson_title": 1,
            "objectives": 4,
            "opening": 3,
            "concept_teaching": 4,
            "guided_practice": 4,
            "concept_reinforcement": 3,
            "independent_practice": 3,
            "assessment": 4,
            "closure": 3,
            "teaching_tips": 4,
            "learn_more": 1,
        }
        max_lines = max_lines_by_section.get(section_key, 4)
        limited: list[str] = []
        seen: set[str] = set()
        for line in lines:
            normalized = re.sub(r"\s+", " ", line).strip().casefold()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            limited.append(line)
            if len(limited) >= max_lines:
                break
        return limited

    def _as_bullets(self, lines: list[str], *, force_bullet: bool) -> list[str]:
        output: list[str] = []
        for line in lines:
            value = line.strip()
            if not value:
                continue
            if self._is_timing_line(value):
                continue
            if force_bullet:
                value = self._strip_list_marker(value)
                output.append(f"- {value}")
            else:
                output.append(value)
        return output

    def _as_plain_lines(self, lines: list[str]) -> list[str]:
        return [self._strip_list_marker(line).strip() for line in lines if line.strip()]

    def _fallback_section_lines(self, section_key: str, topic: str, *, preferred_language: str = "English") -> list[str]:
        if self._is_hindi_language(preferred_language):
            fallback_map = {
                "opening": [
                    f"प्रश्न: {topic.strip()} के बारे में आप पहले से क्या जानते हैं?",
                    "शिक्षक गतिविधि: एक छोटे उदाहरण से बच्चों का ध्यान जोड़ें",
                    "जोड़ी चर्चा: विद्यार्थी एक विचार साझा करें",
                ],
                "concept_teaching": [
                    f"{topic.strip()} की मुख्य अवधारणा को सरल भाषा में समझाएँ",
                    "2 से 3 ज़रूरी बिंदु बच्चों को याद कराएँ",
                    "एक छोटा कक्षा उदाहरण या प्रदर्शन करें",
                ],
                "guided_practice": [
                    "गतिविधि: छोटी जोड़ी या पूरी कक्षा का कार्य कराएँ",
                    "विद्यार्थी कार्य: देखें, चर्चा करें, छाँटें, हल करें या उत्तर दें",
                    "शिक्षक जाँच: कार्य के दौरान छोटे प्रश्न पूछें",
                ],
                "concept_reinforcement": [
                    "मुख्य विचार को छोटे बिंदुओं में दोहराएँ",
                    "एक सही विचार की सामान्य भ्रम से तुलना करें",
                ],
                "independent_practice": [
                    "2 से 3 छोटे लिखित या मौखिक उत्तर लें",
                    "कार्य को मुख्य सीख पर केंद्रित रखें",
                ],
                "assessment": [
                    "त्वरित जाँच: मुख्य विचार क्या है?",
                    "त्वरित जाँच: एक ज़रूरी शब्द या तथ्य क्या है?",
                    "त्वरित जाँच: इसे साथी को कैसे समझाएँगे?",
                ],
                "closure": [
                    f"समापन: {topic.strip()} की मुख्य सीख दोहराएँ",
                    "एग्ज़िट टिकट: आज मैंने एक नई बात सीखी _____",
                ],
            }
            return fallback_map.get(section_key, [])

        fallback_map = {
            "opening": [
                f"Hook Question: What do you already know about {topic.strip()}?",
                "Teacher Move: Start with one quick example or observation",
                "Quick Pair Prompt: Let students share one first idea",
            ],
            "concept_teaching": [
                f"Teach the main concept behind {topic.strip()} in simple language",
                "Highlight 2 to 3 key points students must remember",
                "Use one short classroom example or demo",
            ],
            "guided_practice": [
                "Activity: Run one short pair or whole-class task",
                "Student Action: Observe, discuss, sort, solve, or respond",
                "Teacher Check: Ask short questions during the task",
            ],
            "concept_reinforcement": [
                "Repeat the key idea in short bullets",
                "Compare one correct idea with one common confusion",
            ],
            "independent_practice": [
                "Ask for 2 to 3 short written or oral responses",
                "Keep the task focused on the main learning",
            ],
            "assessment": [
                "Quick Check: What is the main idea?",
                "Quick Check: What is one important fact or term?",
                "Quick Check: How would you explain it to a classmate?",
            ],
            "closure": [
                f"Wrap-Up: Summarize the key takeaway from {topic.strip()}",
                "Exit Ticket: One new thing I learned today is _____",
            ],
        }
        return fallback_map.get(section_key, [])

    def _build_planning_block(
        self,
        *,
        topic: str,
        grade: str,
        subject: str,
        duration_minutes: int,
        preferred_language: str = "English",
    ) -> str:
        if self._is_hindi_language(preferred_language):
            return (
                "पाठ योजना\n"
                f"टॉपिक: {topic.strip()}\n"
                f"ग्रेड/कक्षा: {grade.strip()}\n"
                f"विषय: {subject.strip()}\n"
                f"अवधि: {int(duration_minutes)} minutes"
            )
        return (
            "Lesson Planning\n"
            f"Topic: {topic.strip()}\n"
            f"Grade/Class: {grade.strip()}\n"
            f"Subject: {subject.strip()}\n"
            f"Duration: {int(duration_minutes)} minutes"
        )

    def _is_hindi_language(self, preferred_language: str) -> bool:
        return preferred_language.strip().casefold() == "hindi"

    def _labels_for_language(self, preferred_language: str) -> dict[str, str]:
        if self._is_hindi_language(preferred_language):
            return {
                "lesson_title": "पाठ शीर्षक",
                "objectives": "उद्देश्य",
                "opening": "1. शुरुआत",
                "concept_teaching": "2. अवधारणा शिक्षण",
                "guided_practice": "3. निर्देशित अभ्यास",
                "concept_reinforcement": "4. अवधारणा सुदृढ़ीकरण",
                "independent_practice": "5. स्वतंत्र अभ्यास",
                "assessment": "6. मूल्यांकन / जाँच",
                "closure": "7. समापन",
                "teaching_tips": "शिक्षण सुझाव",
                "learn_more": "और सीखें",
            }
        return {
            "lesson_title": "Lesson Title",
            "objectives": "Objectives",
            "opening": "1. Opening",
            "concept_teaching": "2. Concept Teaching",
            "guided_practice": "3. Guided Practice",
            "concept_reinforcement": "4. Concept Reinforcement",
            "independent_practice": "5. Independent Practice",
            "assessment": "6. Assessment / Check",
            "closure": "7. Closure",
            "teaching_tips": "Teaching Tips",
            "learn_more": "Learn More",
        }

    def _localize_hindi_bullet_label(self, value: str, preferred_language: str) -> str:
        if not self._is_hindi_language(preferred_language):
            return value

        label_map = {
            "Hook Question": "प्रश्न",
            "Teacher Move": "शिक्षक गतिविधि",
            "Quick Pair Prompt": "जोड़ी चर्चा",
            "Activity": "गतिविधि",
            "Student Action": "विद्यार्थी कार्य",
            "Teacher Check": "शिक्षक जाँच",
            "Quick Check": "त्वरित जाँच",
            "Wrap-Up": "समापन",
            "Exit Ticket": "एग्ज़िट टिकट",
        }
        for english_label, hindi_label in label_map.items():
            value = re.sub(
                rf"(?i)^{re.escape(english_label)}\s*:",
                f"{hindi_label}:",
                value,
            )
        return value

    def _extract_llm_source_block(self, text: str) -> str:
        lines = [line.rstrip() for line in text.splitlines()]
        start_index: int | None = None

        for index, line in enumerate(lines):
            stripped = line.strip()
            lowered = stripped.casefold().rstrip(":")
            if lowered in {"source", "स्रोत"} or lowered.startswith("source:") or lowered.startswith("स्रोत:"):
                start_index = index
                break

        if start_index is None:
            return ""

        source_lines: list[str] = []
        for line in lines[start_index : start_index + 8]:
            stripped = line.strip()
            if not stripped:
                if source_lines:
                    break
                continue

            lowered = stripped.casefold()
            if source_lines and self._extract_section_key(stripped) not in {None, "source"}:
                break
            if lowered in {"or", "या"} or lowered.startswith(("learn more", "और सीखें", "अधिक सीखें")):
                break
            if "<" in stripped and ">" in stripped:
                continue

            cleaned = self._strip_list_marker(stripped).strip()
            if cleaned:
                source_lines.append(cleaned)

        block = "\n".join(source_lines).strip()
        if not block:
            return ""

        lowered_block = block.casefold()
        if "ncert" not in lowered_block and "एनसीईआरटी" not in block and "एन.सी.ई.आर.टी" not in block:
            return ""

        return block

    def _build_source_block(self, rows: list[dict]) -> str:
        if not rows:
            return ""

        row = rows[0]
        lines = ["Source:", "NCERT"]

        book = row.get("book")
        unit_name = row.get("unit_name") or row.get("chapter")
        topic_name = row.get("topic_name") or row.get("topic") or row.get("chapter")
        book_url = row.get("book_url") or row.get("source_reference")

        if book:
            lines.append(f"Book: {book}")
        if unit_name:
            lines.append(f"Unit: {unit_name}")
        if topic_name:
            lines.append(f"Chapter: {topic_name}")
        """
        if book_url and isinstance(book_url, str) and book_url.startswith(("http://", "https://")):
            lines.append(f"PDF: {book_url}")
        """

        return "\n".join(lines)

    def _is_timing_line(self, text: str) -> bool:
        return bool(
            re.match(
                r"^\(?\s*\d+(?:\s*[–-]\s*\d+)?\s*min\s*\)?$",
                text.strip(),
                re.IGNORECASE,
            )
        )

    def _is_top_summary_line(self, text: str) -> bool:
        lowered = text.strip().casefold()
        return lowered.startswith(
            (
                "topic -",
                "topic:",
                "grade/class -",
                "grade/class:",
                "subject -",
                "subject:",
                "duration -",
                "duration:",
                "टॉपिक -",
                "टॉपिक:",
                "विषय -",
                "विषय:",
                "ग्रेड/कक्षा -",
                "ग्रेड/कक्षा:",
                "कक्षा -",
                "कक्षा:",
                "अवधि -",
                "अवधि:",
            )
        )

    def _normalize_inline_markdown(self, text: str) -> str:
        value = text.strip()
        value = re.sub(r"^#{1,6}\s*", "", value)
        value = re.sub(r"^\*\*(.*?)\*\*$", r"\1", value).strip()
        value = re.sub(r"^__(.*?)__$", r"\1", value).strip()
        value = re.sub(r"^`(.*?)`$", r"\1", value).strip()
        return value

    def _strip_list_marker(self, text: str) -> str:
        value = text.strip()
        value = re.sub(r"^(?:[-•*]+|\d+[\.)-])\s*", "", value)
        return value.strip()

    def _strip_leading_emoji(self, text: str) -> str:
        value = text.strip()
        value = re.sub(r"^[^\w\s#*`(\-]+\s*", "", value)
        return value.strip()

    def _looks_like_heading(self, text: str) -> bool:
        return self._extract_section_key(text) is not None

    def _find_youtube_url(self, lines: list[str]) -> str | None:
        for line in lines:
            match = re.search(
                r"https?://(?:www\.)?(?:youtube\.com|youtu\.be)/\S+",
                line,
                flags=re.IGNORECASE,
            )
            if match:
                return self._make_url_display_friendly(match.group(0))
        return None

    def _make_url_display_friendly(self, url: str) -> str:
        if "youtube.com/results?search_query=" in url:
            return unquote(url)
        return url

    def _youtube_query(self, topic: str, subject: str) -> str:
        query = f"{topic} {subject} lesson for students"
        return re.sub(r"\s+", "+", query.strip())

    def _allocate_timings(self, duration: int) -> dict[str, int]:
        total = max(20, int(duration))
        opening = max(4, round(total * 0.12))
        concept_teaching = max(8, round(total * 0.28))
        guided_practice = max(5, round(total * 0.20))
        concept_reinforcement = max(4, round(total * 0.14))
        independent_practice = max(4, round(total * 0.12))
        assessment = max(3, round(total * 0.08))
        used = (
            opening
            + concept_teaching
            + guided_practice
            + concept_reinforcement
            + independent_practice
            + assessment
        )
        closure = max(2, total - used)

        return {
            "opening": opening,
            "concept_teaching": concept_teaching,
            "guided_practice": guided_practice,
            "concept_reinforcement": concept_reinforcement,
            "independent_practice": independent_practice,
            "assessment": assessment,
            "closure": closure,
        }

    def _sentence_case(self, value: str, *, keep_short: bool = False) -> str:
        value = value.strip()
        if not value:
            return ""
        if re.match(r"^[A-Z]{2,}(?:\b|$)", value):
            return value
        if keep_short and len(value.split()) <= 3:
            return value[:1].upper() + value[1:]
        return value[:1].upper() + value[1:]

    def _title_case(self, value: str) -> str:
        small_words = {"a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "nor", "of", "on", "or", "the", "to", "vs", "via", "with"}
        words = value.split()
        result: list[str] = []
        for index, word in enumerate(words):
            if word.isupper():
                result.append(word)
                continue
            lowered = word.casefold()
            if index > 0 and lowered in small_words:
                result.append(lowered)
            else:
                result.append(word[:1].upper() + word[1:].lower())
        return " ".join(result)
