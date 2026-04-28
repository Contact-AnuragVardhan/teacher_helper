from __future__ import annotations

import re
from typing import Any


class LessonPayloadBuilder:
    def build(
        self,
        *,
        teacher_id: int,
        lesson_name: str,
        grade: str,
        subject: str,
        topic: str,
        duration_minutes: int,
        lesson_text: str,
    ) -> dict[str, Any]:
        sections = self._parse_sections(lesson_text)
        source_type, source_reference = self._extract_source_metadata(
            lesson_text=lesson_text,
            grade=grade,
            subject=subject,
            topic=topic,
        )

        return {
            "teacher_id": f"teacher-{teacher_id:03d}",
            "lesson_name": lesson_name.strip(),
            "grade": grade.strip(),
            "subject": subject.strip(),
            "topic": topic.strip(),
            "duration_minutes": int(duration_minutes),
            "source_type": source_type,
            "source_reference": source_reference,
            "lesson_json": {
                "lesson_title": self._join_lines(sections.get("lesson_title", [])),
                "objective": self._join_lines(sections.get("objectives", [])),
                "opening": self._join_lines(sections.get("opening", [])),
                "main_teaching": self._join_lines(sections.get("concept_teaching", [])),
                "activity": self._join_lines(
                    sections.get("guided_practice", [])
                    + sections.get("concept_reinforcement", [])
                    + sections.get("independent_practice", [])
                ),
                "qa": sections.get("assessment", []),
                "closing": self._join_lines(sections.get("closure", [])),
                "teaching_tips": sections.get("teaching_tips", []),
            },
        }

    def _parse_sections(self, lesson_text: str) -> dict[str, list[str]]:
        section_map = {
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

        sections: dict[str, list[str]] = {}
        current_key: str | None = None

        for raw_line in lesson_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            if line.casefold() in {"lesson planning", "पाठ योजना"}:
                continue

            if self._is_metadata_line(line):
                continue

            normalized_heading = self._normalize_heading(line)
            mapped = section_map.get(normalized_heading)
            if mapped == "source":
                current_key = None
                continue
            if mapped:
                current_key = mapped
                sections.setdefault(current_key, [])
                continue

            if current_key is None:
                continue

            cleaned = self._strip_bullet(line)
            if cleaned:
                sections.setdefault(current_key, []).append(cleaned)

        return sections

    def _extract_source_metadata(
        self,
        *,
        lesson_text: str,
        grade: str,
        subject: str,
        topic: str,
    ) -> tuple[str, dict[str, Any]]:
        lines = [line.strip() for line in lesson_text.splitlines() if line.strip()]

        source_type = "generated"
        source_reference: dict[str, Any] = {
            "grade": grade.strip(),
            "subject": subject.strip(),
            "topic_name": topic.strip(),
        }

        source_index = self._find_source_index(lines)
        if source_index is None:
            return source_type, source_reference

        first_source_line = lines[source_index]
        following = [first_source_line] + lines[source_index + 1 : source_index + 8]
        source_blob = "\n".join(following)

        if "ncert" in source_blob.casefold() or "एनसीईआरटी" in source_blob or "एन.सी.ई.आर.टी" in source_blob:
            source_type = "ncert_syllabus"

        for line in following:
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip().casefold()
            value = value.strip()
            if not value or ("<" in value and ">" in value):
                continue
            if key == "source" and "ncert" in value.casefold():
                source_type = "ncert_syllabus"
            elif key == "book":
                source_reference["book"] = value
            elif key == "unit":
                source_reference["unit"] = value
            elif key == "chapter":
                source_reference["chapter"] = value
                source_reference["topic_name"] = value

        return source_type, source_reference

    def _find_source_index(self, lines: list[str]) -> int | None:
        for index, line in enumerate(lines):
            normalized = self._normalize_heading(line)
            lowered = line.casefold().strip()
            if normalized in {"source", "स्रोत"} or lowered.startswith("source:") or lowered.startswith("स्रोत:"):
                return index
        return None

    def _normalize_heading(self, line: str) -> str:
        return re.sub(r"\s*\([^)]*\)\s*$", "", line.rstrip(":").strip()).casefold()

    def _strip_bullet(self, line: str) -> str:
        return re.sub(r"^(?:[-•*]+|\d+[\.)-])\s*", "", line).strip()

    def _is_metadata_line(self, line: str) -> bool:
        lowered = line.casefold()
        return lowered.startswith(
            (
                "topic:",
                "topic -",
                "grade/class:",
                "grade/class -",
                "subject:",
                "subject -",
                "duration:",
                "duration -",
                "टॉपिक:",
                "टॉपिक -",
                "ग्रेड/कक्षा:",
                "ग्रेड/कक्षा -",
                "कक्षा:",
                "कक्षा -",
                "विषय:",
                "विषय -",
                "अवधि:",
                "अवधि -",
            )
        )

    def _join_lines(self, values: list[str]) -> str:
        return " ".join(value.strip() for value in values if value.strip()).strip()
