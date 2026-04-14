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
            "source": "source",
        }

        sections: dict[str, list[str]] = {}
        current_key: str | None = None

        for raw_line in lesson_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            if line.casefold() == "lesson planning":
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

        if "Source:" in lines:
            source_index = lines.index("Source:")
            following = lines[source_index + 1 : source_index + 8]

            if any(line.casefold() == "ncert" for line in following):
                source_type = "ncert_syllabus"

            for line in following:
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                key = key.strip().casefold()
                value = value.strip()
                if not value:
                    continue
                if key == "book":
                    source_reference["book"] = value
                elif key == "unit":
                    source_reference["unit"] = value
                elif key == "chapter":
                    source_reference["chapter"] = value
                    source_reference["topic_name"] = value

        return source_type, source_reference

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
            )
        )

    def _join_lines(self, values: list[str]) -> str:
        return " ".join(value.strip() for value in values if value.strip()).strip()