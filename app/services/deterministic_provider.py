from app.core.logging import get_logger, log_event
from app.services.lesson_generation_provider import LessonGenerationProvider, PromptBundle

logger = get_logger(__name__)


class DeterministicTemplateProvider(LessonGenerationProvider):
    provider_name = "deterministic"

    def generate(self, prompt: PromptBundle) -> str:
        log_event(logger, "deterministic_generation_started", topic=prompt.metadata.get("topic"))
        topic = str(prompt.metadata.get("topic", "Lesson")).strip()
        subject = str(prompt.metadata.get("subject", "the subject")).strip()
        duration = int(prompt.metadata.get("duration_minutes", 35))

        opening, main_teaching, activity, qa, closing = self._allocate_minutes(duration)

        return (
            f"Lesson Title\n"
            f"{self._title_case(topic)}\n\n"
            f"Objective\n"
            f"Students will build understanding of {topic} through explanation, class discussion, guided examples, and a short learning task in {subject}.\n\n"
            f"Opening\n"
            f"({opening} min) Introduce the topic with a short classroom prompt that connects it to students' prior knowledge and explain the learning focus for the period.\n\n"
            f"Main Teaching\n"
            f"({main_teaching} min)\n"
            f"- Introduce the core idea of the topic in simple, grade-appropriate language.\n"
            f"- Explain the most important points step by step and connect them to the chapter or lesson focus.\n"
            f"- Use one or two relevant examples to clarify understanding.\n"
            f"- Check comprehension with brief oral questions during teaching.\n\n"
            f"Activity\n"
            f"({activity} min) Give students a short written, oral, or pair-based task so they can apply the main idea and share their responses.\n\n"
            f"Q&A\n"
            f"({qa} min)\n"
            f"- What is the main idea of this lesson?\n"
            f"- Which example or explanation helped you understand it better?\n"
            f"- What is one important point you will remember from today?\n\n"
            f"Closing\n"
            f"({closing} min) Recap the key learning in simple points, reconnect it to the objective, and invite students to state one takeaway from the lesson."
        )

    def _allocate_minutes(self, duration: int) -> tuple[int, int, int, int, int]:
        opening = max(4, round(duration * 0.12))
        main_teaching = max(15, round(duration * 0.50))
        activity = max(5, round(duration * 0.16))
        qa = max(4, round(duration * 0.12))
        used = opening + main_teaching + activity + qa
        closing = max(2, duration - used)
        return opening, main_teaching, activity, qa, closing

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
