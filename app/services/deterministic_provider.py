from app.core.logging import get_logger, log_event
from app.services.lesson_generation_provider import LessonGenerationProvider, PromptBundle

logger = get_logger(__name__)


class DeterministicTemplateProvider(LessonGenerationProvider):
    provider_name = "deterministic"

    def generate(self, prompt: PromptBundle) -> str:
        log_event(logger, "deterministic_generation_started", topic=prompt.metadata.get("topic"))
        topic = str(prompt.metadata.get("topic", "Lesson")).strip()
        grade = str(prompt.metadata.get("grade", "the class")).strip()
        subject = str(prompt.metadata.get("subject", "the subject")).strip()
        duration = int(prompt.metadata.get("duration_minutes", 35))
        rows = list(prompt.metadata.get("matched_syllabus_rows", []))
        primary_row = rows[0] if rows else {}

        opening, main_teaching, activity, qa, closing = self._allocate_minutes(duration)

        if subject.casefold() == "english":
            lesson = self._build_english_lesson(
                topic=topic,
                grade=grade,
                opening=opening,
                main_teaching=main_teaching,
                activity=activity,
                qa=qa,
                closing=closing,
                row=primary_row,
            )
        else:
            lesson = self._build_general_lesson(
                topic=topic,
                grade=grade,
                subject=subject,
                opening=opening,
                main_teaching=main_teaching,
                activity=activity,
                qa=qa,
                closing=closing,
                row=primary_row,
            )

        source_block = self._build_source_block(primary_row)
        return f"{lesson}\n\n{source_block}" if source_block else lesson

    def _allocate_minutes(self, duration: int) -> tuple[int, int, int, int, int]:
        opening = max(5, round(duration * 0.12))
        main_teaching = max(18, round(duration * 0.50))
        activity = max(5, round(duration * 0.15))
        qa = max(5, round(duration * 0.13))
        used = opening + main_teaching + activity + qa
        closing = max(3, duration - used)
        return opening, main_teaching, activity, qa, closing

    def _build_english_lesson(
        self,
        *,
        topic: str,
        grade: str,
        opening: int,
        main_teaching: int,
        activity: int,
        qa: int,
        closing: int,
        row: dict,
    ) -> str:
        chapter_label = row.get("topic_name") or row.get("chapter") or topic
        author_line = self._author_line(row)

        return (
            f"Lesson Title\n"
            f"{self._title_case(topic)}\n\n"
            f"Objective\n"
            f"Students will understand the main ideas in {chapter_label}, analyze important characters or relationships, "
            f"identify the central theme or message, and express their responses in simple, clear language.\n\n"
            f"Opening\n"
            f"({opening} min) Ask students a simple real-life question connected to the lesson theme and invite 2-3 quick responses. "
            f"Then connect their answers to {chapter_label} and explain what they will learn today.\n\n"
            f"Main Teaching\n"
            f"({main_teaching} min)\n"
            f"- Introduce the author and the context of the lesson.{author_line}\n"
            f"- Explain the important character(s), habits, actions, or feelings shown in the text.\n"
            f"- Trace how the relationship, situation, or point of view develops through the lesson.\n"
            f"- Highlight the main themes, values, and message in simple language.\n"
            f"- Read and explain important excerpts, vocabulary, and textbook questions where relevant.\n\n"
            f"Activity\n"
            f"({activity} min) Students write 3-4 lines about a family elder, a memorable relationship, or a personal experience connected to the lesson theme, using descriptive details and simple language.\n\n"
            f"Q&A\n"
            f"({qa} min)\n"
            f"- Who is the central figure or important character in the lesson?\n"
            f"- What change in relationship, thinking, or situation do we notice in the text?\n"
            f"- Which detail from the chapter best shows the character or theme?\n"
            f"- What value or message do you learn from this lesson?\n\n"
            f"Closing\n"
            f"({closing} min) Summarize the main idea of the lesson, revisit the objective, and ask students to share one value, feeling, or insight they learned from the text."
        )

    def _build_general_lesson(
        self,
        *,
        topic: str,
        grade: str,
        subject: str,
        opening: int,
        main_teaching: int,
        activity: int,
        qa: int,
        closing: int,
        row: dict,
    ) -> str:
        chapter_label = row.get("topic_name") or row.get("chapter") or topic
        return (
            f"Lesson Title\n"
            f"{self._title_case(topic)}\n\n"
            f"Objective\n"
            f"Students will understand the key ideas of {chapter_label}, participate in class discussion, and apply the learning in simple classroom tasks.\n\n"
            f"Opening\n"
            f"({opening} min) Begin with a short question, example, or everyday situation connected to {chapter_label} so students can link the topic to prior knowledge.\n\n"
            f"Main Teaching\n"
            f"({main_teaching} min)\n"
            f"- Introduce the topic and explain why it is important in {subject}.\n"
            f"- Teach the main concept step by step in simple language.\n"
            f"- Use 1-2 examples from daily life or the textbook.\n"
            f"- Clarify important terms, ideas, or processes.\n"
            f"- Check understanding with brief oral questions during explanation.\n\n"
            f"Activity\n"
            f"({activity} min) Give students one short individual or pair task so they can apply the concept and share their answers with the class.\n\n"
            f"Q&A\n"
            f"({qa} min)\n"
            f"- What is the main idea of this topic?\n"
            f"- Which example from class helped you understand it better?\n"
            f"- What is one important term or point you remember?\n"
            f"- How can you explain this topic in your own words?\n\n"
            f"Closing\n"
            f"({closing} min) Recap the lesson in simple points, connect it back to the objective, and ask students to state one thing they learned today."
        )

    def _build_source_block(self, row: dict) -> str:
        if not row:
            return ""

        lines = ["Source", "NCERT"]
        book = row.get("book")
        chapter = row.get("topic_name") or row.get("chapter") or row.get("unit_name")
        if book:
            lines.append(f"Book: {book}")
        if chapter:
            lines.append(f"Chapter: {chapter}")
        return "\n".join(lines)

    def _author_line(self, row: dict) -> str:
        summary = str(row.get("topic_summary") or "")
        if not summary:
            return ""

        candidates = []
        for piece in summary.replace("\n", " ").split("."):
            text = piece.strip()
            if not text:
                continue
            candidates.append(text)
            if len(candidates) == 2:
                break
        if not candidates:
            return ""
        return ""

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
