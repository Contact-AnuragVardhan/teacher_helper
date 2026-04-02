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


class PromptBuilder:
    def build(self, data: PromptBuilderInput) -> PromptBundle:
        context_block = "\n\n---\n\n".join(data.retrieved_snippets[:3]).strip()
        if not context_block:
            context_block = (
                "No NCERT syllabus row was retrieved. "
                "Use a safe, classroom-ready deterministic lesson structure and clearly stay generic."
            )

        system_prompt = (
            "You are a lesson planning assistant for Indian K-12 teachers. "
            "Stay aligned to the provided NCERT syllabus context. "
            "Do not drift outside the matched syllabus row unless a detail is absolutely required for classroom clarity. "
            "Use simple teacher-friendly language. "
            "Return exactly these sections and no extra commentary: "
            "Lesson Title, Objective, Opening, Main Teaching, Activity, Q&A, Closing."
        )

        user_prompt = (
            f"Teacher request\n"
            f"Grade: {data.grade}\n"
            f"Subject: {data.subject}\n"
            f"Preferred language: {data.preferred_language}\n"
            f"Topic: {data.topic}\n"
            f"Duration (minutes): {data.duration_minutes}\n\n"
            f"Matched NCERT syllabus context\n"
            f"{context_block}\n\n"
            "Instructions\n"
            "- Build the lesson around the matched syllabus context above.\n"
            "- Keep the output concise and classroom-ready.\n"
            "- Make the plan duration-aware.\n"
            "- Use only the exact section headings below.\n"
            "- No markdown bullets are required, but short lists are okay inside sections if natural.\n"
            "- Do not add Teacher Notes, References, or any extra headings."
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
            },
        )