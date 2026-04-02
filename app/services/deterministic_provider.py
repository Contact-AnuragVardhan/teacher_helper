import re

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
        snippets = list(prompt.metadata.get("retrieved_snippets", []))

        opening = max(3, duration // 6)
        main_teaching = max(10, duration // 2)
        activity = max(5, duration // 5)
        qa = max(4, duration // 8)
        used = opening + main_teaching + activity + qa
        closing = max(2, duration - used)

        key_points = self._extract_key_points(snippets)
        knowledge_line = " ".join(key_points) if key_points else f"Explain the core idea of {topic}."
        activity_line = self._activity_line(topic, snippets)
        questions = self._question_line(topic)

        return (
            f"Lesson Title\n"
            f"{topic.title()}\n\n"
            f"Objective\n"
            f"Students in Grade {grade} will understand the main idea of {topic} in {subject} and explain it in simple words.\n\n"
            f"Opening\n"
            f"({opening} min) Begin with a familiar question or example related to {topic} and connect it to what students already know.\n\n"
            f"Main Teaching\n"
            f"({main_teaching} min) {knowledge_line}\n\n"
            f"Activity\n"
            f"({activity} min) {activity_line}\n\n"
            f"Q&A\n"
            f"({qa} min) {questions}\n\n"
            f"Closing\n"
            f"({closing} min) Summarize the main learning, revisit the objective, and ask students to share one thing they learned about {topic}."
        )

    def _extract_key_points(self, snippets: list[str]) -> list[str]:
        sentences: list[str] = []
        for snippet in snippets[:3]:
            cleaned = re.sub(r"\s+", " ", snippet).strip()
            for sentence in re.split(r"(?<=[.!?])\s+", cleaned):
                candidate = sentence.strip()
                if candidate:
                    sentences.append(candidate)
            if len(sentences) >= 2:
                break
        return sentences[:2]

    def _activity_line(self, topic: str, snippets: list[str]) -> str:
        if snippets:
            return (
                f"Ask students to work in pairs and note one example, observation, or explanation from the lesson on {topic}, "
                "then share it with the class."
            )
        return f"Ask students to do one short notebook or pair activity connected to {topic}."

    def _question_line(self, topic: str) -> str:
        return (
            f"Ask 2-3 quick questions: What is {topic}? Why is it important? Can you give one example in your own words?"
        )
