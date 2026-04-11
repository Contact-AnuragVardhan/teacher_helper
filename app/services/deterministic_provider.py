import re

from app.core.logging import get_logger, log_event
from app.services.lesson_generation_provider import LessonGenerationProvider, PromptBundle

logger = get_logger(__name__)


class DeterministicTemplateProvider(LessonGenerationProvider):
    provider_name = "deterministic"

    def generate(self, prompt: PromptBundle) -> str:
        log_event(logger, "deterministic_generation_started", topic=prompt.metadata.get("topic"))
        topic = str(prompt.metadata.get("topic", "Lesson")).strip()
        grade = str(prompt.metadata.get("grade", "")).strip()
        subject = str(prompt.metadata.get("subject", "the subject")).strip()
        duration = int(prompt.metadata.get("duration_minutes", 35))
        preferred_language = str(prompt.metadata.get("preferred_language", "English")).strip().casefold()
        has_ncert_match = bool(prompt.metadata.get("has_ncert_match"))

        timings = self._allocate_timings(duration)
        if preferred_language == "hinglish":
            return self._build_hinglish(topic, grade, subject, duration, timings, has_ncert_match)
        return self._build_english(topic, grade, subject, duration, timings, has_ncert_match)

    def _build_english(self, topic: str, grade: str, subject: str, duration: int, timings: dict[str, int], has_ncert_match: bool) -> str:
        lines = [
            "Lesson Planning",
            f"Topic: {topic}",
            f"Grade/Class: {grade}",
            f"Subject: {subject}",
            f"Duration: {duration} minutes",
            "",
            "Lesson Title",
            f"- {self._title_case(topic)}",
            "",
            "Objectives",
            f"- Understand the core idea of {topic}.",
            f"- Explain key points from {topic} in simple words.",
            f"- Apply the learning from {topic} in class discussion or practice.",
            "",
            f"1. Opening ({timings['opening']} min)",
            f"- Hook Question: What do you already know about {topic}?",
            f"- Teacher Move: Activate prior knowledge with one quick classroom example.",
            f"- Quick Pair Prompt: Share one idea or observation related to {topic}.",
            "",
            f"2. Concept Teaching ({timings['concept_teaching']} min)",
            f"- Introduce the main concept in simple, grade-appropriate language.",
            f"- Teach 2 to 3 key ideas connected to {topic}.",
            f"- Use one short example or demonstration to make the concept concrete.",
            "",
            f"3. Guided Practice ({timings['guided_practice']} min)",
            "- Activity: Short pair or whole-class guided task.",
            f"- Student Action: Observe, discuss, sort, solve, or respond using the lesson idea.",
            "- Teacher Check: Ask short questions while students are working.",
            "",
            f"4. Concept Reinforcement ({timings['concept_reinforcement']} min)",
            "- Revisit the most important concept in 2 short bullets.",
            "- Compare one correct idea with one common confusion.",
            "",
            f"5. Independent Practice ({timings['independent_practice']} min)",
            "- Ask students to answer 2 to 3 short written or oral prompts.",
            f"- Keep the task focused on the main learning from {topic}.",
            "",
            f"6. Assessment / Check ({timings['assessment']} min)",
            "- Quick Check: What is the main idea?",
            "- Quick Check: What is one important term or fact?",
            "- Quick Check: How would you explain this to a classmate?",
            "",
            f"7. Closure ({timings['closure']} min)",
            f"- Wrap-Up: Summarize the key takeaway from {topic}.",
            "- Exit Ticket: One new thing I learned today is _____.",
            "",
            "Teaching Tips",
            "- Keep explanations short and check understanding often.",
            "- Use board work, body movement, or a quick demo instead of long theory.",
            "- Treat this as a classroom plan, then expand verbally while teaching.",
        ]

        if not has_ncert_match:
            lines.extend(
                [
                    "",
                    "Learn More",
                    f"- https://www.youtube.com/results?search_query={self._youtube_query(topic, subject)}",
                ]
            )

        return "\n".join(lines)

    def _build_hinglish(self, topic: str, grade: str, subject: str, duration: int, timings: dict[str, int], has_ncert_match: bool) -> str:
        lines = [
            "Lesson Planning",
            f"Topic: {topic}",
            f"Grade/Class: {grade}",
            f"Subject: {subject}",
            f"Duration: {duration} minutes",
            "",
            "Lesson Title",
            f"- {self._title_case(topic)}",
            "",
            "Objectives",
            f"- {topic} ka basic idea samajhna.",
            f"- {topic} ke key points simple words mein batana.",
            f"- Class discussion ya practice mein concept apply karna.",
            "",
            f"1. Opening ({timings['opening']} min)",
            f"- Hook Question: {topic} ke baare mein tum pehle se kya jaante ho?",
            "- Teacher Move: Ek quick example se prior knowledge activate karo.",
            "- Quick Pair Prompt: Pair mein ek idea share karo.",
            "",
            f"2. Concept Teaching ({timings['concept_teaching']} min)",
            "- Main concept ko simple Hinglish mein samjhao.",
            f"- {topic} se jude 2 ya 3 important points lo.",
            "- Ek short example ya demo use karo.",
            "",
            f"3. Guided Practice ({timings['guided_practice']} min)",
            "- Activity: Short pair ya whole-class task.",
            "- Student Action: Observe, discuss, likho, ya answer do.",
            "- Teacher Check: Kaam ke dauran short questions poochho.",
            "",
            f"4. Concept Reinforcement ({timings['concept_reinforcement']} min)",
            "- Sabse important idea ko 2 short bullets mein repeat karo.",
            "- Ek common confusion ko correct answer se compare karo.",
            "",
            f"5. Independent Practice ({timings['independent_practice']} min)",
            "- 2 ya 3 short written/oral responses lo.",
            f"- Task ko {topic} ke main learning point par rakho.",
            "",
            f"6. Assessment / Check ({timings['assessment']} min)",
            "- Quick Check: Main idea kya hai?",
            "- Quick Check: Ek important term ya fact batao.",
            "- Quick Check: Is concept ko friend ko kaise samjhaoge?",
            "",
            f"7. Closure ({timings['closure']} min)",
            f"- Wrap-Up: {topic} ka key takeaway bolo.",
            "- Exit Ticket: Aaj maine ek nayi baat seekhi _____.",
            "",
            "Teaching Tips",
            "- Explanation short rakho aur beech-beech mein check karo.",
            "- Long theory ke bajaay board, movement, ya quick demo use karo.",
            "- Isko teaching plan samjho; details class mein orally expand karo.",
        ]

        if not has_ncert_match:
            lines.extend(
                [
                    "",
                    "Learn More",
                    f"- https://www.youtube.com/results?search_query={self._youtube_query(topic, subject)}",
                ]
            )

        return "\n".join(lines)

    def _allocate_timings(self, duration: int) -> dict[str, int]:
        total = max(20, int(duration))
        opening = max(4, round(total * 0.12))
        concept_teaching = max(8, round(total * 0.28))
        guided_practice = max(5, round(total * 0.20))
        concept_reinforcement = max(4, round(total * 0.14))
        independent_practice = max(4, round(total * 0.12))
        assessment = max(3, round(total * 0.08))
        used = opening + concept_teaching + guided_practice + concept_reinforcement + independent_practice + assessment
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

    def _youtube_query(self, topic: str, subject: str) -> str:
        query = f"{topic} {subject} lesson for students"
        query = re.sub(r"\s+", "+", query.strip())
        return query

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
