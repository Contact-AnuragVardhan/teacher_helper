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

        opening, main_teaching, activity, qa, closing = self._allocate_minutes(duration)

        if preferred_language == "hinglish":
            return (
                f"Lesson Planning\n"
                f"Topic - {topic}\n"
                f"Grade/Class - {grade}\n"
                f"Subject - {subject}\n"
                f"Duration - {duration} min\n\n"
                f"Lesson Title\n"
                f"{self._title_case(topic)}\n\n"
                f"Objective\n"
                f"Students {topic} ka basic idea samjhenge.\n"
                f"Students important points ko simple examples ke saath explain kar paayenge.\n"
                f"Students class discussion aur activity ke through concept apply karenge.\n\n"
                f"Opening\n"
                f"({opening} min)\n"
                f"Hook: Topic se related ek short warm-up question poochiye.\n"
                f"Connect: Students ke prior knowledge ya daily life se topic ko jodiye.\n"
                f"Focus: Aaj ke lesson ka clear learning focus batayiye.\n\n"
                f"Main Teaching\n"
                f"({main_teaching} min)\n"
                f"1. Topic ka basic introduction simple Hinglish mein dijiye.\n"
                f"2. Important concept ya facts ko step by step samjhaiye.\n"
                f"3. Ek ya do relevant examples dijiye taaki understanding clear ho.\n"
                f"4. Topic ko chapter focus ya classroom learning goal se connect kijiye.\n"
                f"5. Beech-beech mein short oral questions poochkar comprehension check kijiye.\n\n"
                f"Activity\n"
                f"({activity} min)\n"
                f"Task: Students ko individual, pair, ya group-based short task dijiye.\n"
                f"Steps: Unse main idea identify karne, likhne, ya discuss karne ko kahiye.\n"
                f"Share: 2-3 students ya pairs apne responses class ke saath share karein.\n\n"
                f"Q&A\n"
                f"({qa} min)\n"
                f"1. Aaj ke lesson ka main idea kya tha?\n"
                f"2. Is topic ka ek important point batao.\n"
                f"3. Kaunsa example ya explanation aapko sabse helpful laga?\n"
                f"4. Is topic ko aap real life ya next lesson se kaise connect karoge?\n\n"
                f"Closing\n"
                f"({closing} min)\n"
                f"Recap: Key learning ko short points mein revise kijiye.\n"
                f"Reflection: Students se ek takeaway ya ek sentence response bulwaiye."
            )

        return (
            f"Lesson Planning\n"
            f"Topic - {topic}\n"
            f"Grade/Class - {grade}\n"
            f"Subject - {subject}\n"
            f"Duration - {duration} min\n\n"
            f"Lesson Title\n"
            f"{self._title_case(topic)}\n\n"
            f"Objective\n"
            f"Students will understand the basic idea of {topic}.\n"
            f"Students will explain important points using simple classroom examples.\n"
            f"Students will apply the concept through discussion and a short activity.\n\n"
            f"Opening\n"
            f"({opening} min)\n"
            f"Hook: Ask a short warm-up question related to the topic.\n"
            f"Connect: Link the topic to prior knowledge or a familiar example.\n"
            f"Focus: State the learning goal for the period clearly.\n\n"
            f"Main Teaching\n"
            f"({main_teaching} min)\n"
            f"1. Introduce the topic in simple, grade-appropriate language.\n"
            f"2. Explain the most important concept or facts step by step.\n"
            f"3. Use one or two relevant examples to make the idea clear.\n"
            f"4. Connect the topic to the chapter focus or classroom objective.\n"
            f"5. Check understanding with brief oral questions during teaching.\n\n"
            f"Activity\n"
            f"({activity} min)\n"
            f"Task: Give students a short individual, pair, or group activity.\n"
            f"Steps: Ask them to identify, discuss, write, or solve based on the main idea.\n"
            f"Share: Invite a few students or pairs to present their responses.\n\n"
            f"Q&A\n"
            f"({qa} min)\n"
            f"1. What is the main idea of today’s lesson?\n"
            f"2. What is one important point you learned?\n"
            f"3. Which example or explanation helped you most?\n"
            f"4. How can you connect this topic to real life or the next lesson?\n\n"
            f"Closing\n"
            f"({closing} min)\n"
            f"Recap: Review the key learning in short points.\n"
            f"Reflection: Ask students to share one takeaway from the lesson."
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