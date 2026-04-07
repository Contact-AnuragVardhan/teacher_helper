from dataclasses import dataclass

from app.services.lesson_generation_provider import PromptBundle


@dataclass(slots=True)
class PromptBuilderInput:
    grade: str
    subject: str
    preferred_language: str
    topic: str
    duration_minutes: int
    retrieved_snippets: list[str]
    matched_syllabus_rows: list[dict]


class PromptBuilder:
    def build(self, data: PromptBuilderInput) -> PromptBundle:
        context_block = "\n\n---\n\n".join(data.retrieved_snippets[:3]).strip()
        has_match = bool(data.matched_syllabus_rows)

        if not context_block:
            context_block = (
                "No NCERT syllabus row was retrieved. "
                "Use a safe, classroom-ready lesson structure and keep the content generic."
            )

        system_prompt = (
            "You are a professional lesson planning assistant for Indian K-12 teachers. "
            "Write polished, classroom-ready lesson plans in simple teacher-friendly language. "
            "Use the NCERT grounding context only to understand the chapter and topic. "
            "Do not copy raw syllabus text, OCR fragments, metadata, URLs, keywords, debug labels, or matched-row dumps into the lesson. "
            "Do not write lines such as Grade:, Subject:, Topic Summary:, Book URL:, Keywords:, or Matched syllabus row. "
            "For literature lessons, relate the text to real-life experiences, values, feelings, relationships, and classroom discussion. "
            "Make the lesson feel like a real teacher's plan, not a data extract. "
            "Return these section titles exactly: Lesson Title, Objective, Opening, Main Teaching, Activity, Q&A, Closing. "
            "Add a final Source section only when NCERT context is clearly matched."
        )

        source_instruction = (
            "- Add a final section titled Source with exactly these lines when NCERT is matched: NCERT, Book: <book if known>, Chapter: <chapter/topic if known>.\n"
            if has_match
            else "- Do not add a Source section when no NCERT match is available.\n"
        )

        user_prompt = (
            f"Teacher request\n"
            f"Grade: {data.grade}\n"
            f"Subject: {data.subject}\n"
            f"Preferred language: {data.preferred_language}\n"
            f"Topic: {data.topic}\n"
            f"Duration (minutes): {data.duration_minutes}\n\n"
            f"Matched NCERT context\n"
            f"{context_block}\n\n"
            "Instructions\n"
            "- Build the lesson around the matched topic.\n"
            "- Keep the tone professional, practical, and teacher-ready.\n"
            "- Make the plan duration-aware.\n"
            "- Use specific teaching moves, not generic filler.\n"
            "- Keep Main Teaching focused on what the teacher will explain in class.\n"
            "- Activity should be short, realistic, and easy to run in a regular classroom.\n"
            "- Q&A should include 3-4 meaningful chapter-based questions.\n"
            "- Do not include markdown tables.\n"
            "- Short bullets inside sections are allowed when helpful.\n"
            f"{source_instruction}"
            "- Do not add any other headings or commentary."
        )

        return PromptBundle(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            metadata={
                "grade": data.grade,
                "subject": data.subject,
                "preferred_language": data.preferred_language,
                "topic": data.topic,
                "duration_minutes": data.duration_minutes,
                "retrieved_snippets": data.retrieved_snippets,
                "matched_syllabus_rows": data.matched_syllabus_rows,
            },
        )
