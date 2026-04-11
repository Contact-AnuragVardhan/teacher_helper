from dataclasses import dataclass, field

from app.core.logging import get_logger, log_event
from app.services.lesson_generation_provider import PromptBundle

logger = get_logger(__name__)


@dataclass(slots=True)
class PromptBuilderInput:
    grade: str
    subject: str
    preferred_language: str
    topic: str
    duration_minutes: int
    retrieved_snippets: list[str]
    matched_syllabus_rows: list[dict] = field(default_factory=list)


class PromptBuilder:
    def build(self, data: PromptBuilderInput) -> PromptBundle:
        has_ncert_match = bool(data.retrieved_snippets)
        context_block = "\n\n---\n\n".join(data.retrieved_snippets[:3]).strip()
        if not context_block:
            context_block = (
                "No NCERT syllabus row matched this topic for the requested grade and subject. "
                "Create the lesson plan for the requested topic itself using general classroom knowledge. "
                "Do not switch to another NCERT chapter or textbook topic."
            )

        log_event(
            logger,
            "prompt_builder_ncert_context_block",
            grade=data.grade,
            subject=data.subject,
            topic=data.topic,
            has_ncert_match=has_ncert_match,
            context_block=context_block,
        )

        timing_map = self._allocate_timings(data.duration_minutes)
        timing_block = (
            f"1. Opening -> ({timing_map['opening']} min)\n"
            f"2. Concept Teaching -> ({timing_map['concept_teaching']} min)\n"
            f"3. Guided Practice -> ({timing_map['guided_practice']} min)\n"
            f"4. Concept Reinforcement -> ({timing_map['concept_reinforcement']} min)\n"
            f"5. Independent Practice -> ({timing_map['independent_practice']} min)\n"
            f"6. Assessment / Check -> ({timing_map['assessment']} min)\n"
            f"7. Closure -> ({timing_map['closure']} min)"
        )

        language_instruction = self._language_instruction(data.preferred_language)
        content_depth_instruction = self._content_depth_instruction(data.subject)

        system_prompt = (
            "You are a lesson planning assistant for Indian K-12 teachers. "
            "The task is Lesson Planning. "
            "Return plain text only. "
            "The output must be easy to read on a smartphone and suitable for WhatsApp. "
            "Use short bullet points with limited text. This is a plan, not a long script. "
            "Keep strong boundaries between sections using blank lines. "
            "Do not write any preface such as 'Here is your generated lesson plan'. "
            "Do not use markdown tables. Do not write long paragraphs. Do not add commentary outside the lesson plan. "
            "Use these visible sections in this order: Lesson Title, Objectives, 1. Opening, 2. Concept Teaching, 3. Guided Practice, "
            "4. Concept Reinforcement, 5. Independent Practice, 6. Assessment / Check, 7. Closure, Teaching Tips. "
            "Use Learn More only when no NCERT match exists. "
            "Never add a Source section yourself because the app will add it when NCERT data exists. "
            f"{language_instruction}"
        )

        if has_ncert_match:
            match_instruction = (
                "- Build the lesson around the matched NCERT syllabus context above.\n"
                "- Keep the teaching plan chapter-aware and classroom-ready.\n"
                "- Use the actual NCERT concepts, events, people, themes, or skills present in the retrieved context.\n"
                "- Do not invent other books, chapters, or external sources.\n"
                "- Do not include a YouTube link.\n"
                "- Do not include a Learn More section. The app will append the Source section separately.\n"
            )
        else:
            match_instruction = (
                "- No NCERT syllabus match was found. Build the lesson for the requested topic itself.\n"
                "- Do not substitute another chapter or textbook topic.\n"
                "- Add a Learn More section at the end with exactly one student-friendly YouTube link relevant to the requested topic.\n"
            )

        user_prompt = (
            f"Teacher request\n"
            f"Grade/Class: {data.grade}\n"
            f"Subject: {data.subject}\n"
            f"Preferred language: {data.preferred_language}\n"
            f"Topic: {data.topic}\n"
            f"Duration (minutes): {data.duration_minutes}\n\n"
            f"NCERT syllabus context\n"
            f"{context_block}\n\n"
            "Instructions\n"
            f"{match_instruction}"
            "- Start immediately with the summary block. Do not add any intro sentence before it.\n"
            "- Start with this exact summary block:\n"
            "  Lesson Planning\n"
            f"  Topic: {data.topic}\n"
            f"  Grade/Class: {data.grade}\n"
            f"  Subject: {data.subject}\n"
            f"  Duration: {data.duration_minutes} minutes\n"
            "- Use the exact section headings and order requested.\n"
            "- Put the timing in the same heading line for sections 1 to 7, for example: '1. Opening (6 min)'.\n"
            "- This is a plan, not details. Expect the teacher to generate details in class.\n"
            "- Keep each bullet short. Prefer 2 to 4 bullets per section. Never exceed 4 bullets in a section.\n"
            "- Prefer brief classroom-ready phrases over long explanatory sentences.\n"
            "- Use classroom-friendly wording like Hook Question, Teacher Move, Ask, Activity, Quick Check, Exit Ticket when useful.\n"
            "- No markdown tables. If comparison is needed, express it as bullets.\n"
            "- Objectives should be short bullet points, not long sentences.\n"
            "- Teaching Tips should be 2 to 4 short bullets focused on delivery.\n"
            f"- {content_depth_instruction}\n"
            f"- {language_instruction}\n"
            "- Avoid generic filler such as 'Introduce the topic', 'Explain the concept', 'Use examples', or 'Review the lesson'. "
            "Replace them with the actual teaching moves, actual concepts, and actual student tasks for this topic.\n"
            f"- Use this time distribution exactly:\n{timing_block}\n\n"
            "Return in this exact plain-text shape:\n"
            "Lesson Planning\n"
            "Topic: <requested topic>\n"
            "Grade/Class: <grade>\n"
            "Subject: <subject>\n"
            "Duration: <duration> minutes\n\n"
            "Lesson Title\n"
            "- <short topic-specific title>\n\n"
            "Objectives\n"
            "- <objective 1>\n"
            "- <objective 2>\n"
            "- <objective 3>\n\n"
            "1. Opening (<time>)\n"
            "- Hook Question: <short hook>\n"
            "- Teacher Move: <short move>\n"
            "- Quick Pair Prompt: <short student prompt>\n\n"
            "2. Concept Teaching (<time>)\n"
            "- <concept point 1>\n"
            "- <concept point 2>\n"
            "- <concept point 3>\n\n"
            "3. Guided Practice (<time>)\n"
            "- Activity: <short activity title>\n"
            "- Student Action: <what students do>\n"
            "- Teacher Check: <what teacher asks or checks>\n\n"
            "4. Concept Reinforcement (<time>)\n"
            "- <short compare, contrast, or reinforce bullet>\n"
            "- <short reinforce bullet>\n\n"
            "5. Independent Practice (<time>)\n"
            "- <short independent task>\n"
            "- <short response prompt>\n\n"
            "6. Assessment / Check (<time>)\n"
            "- <short check question or rapid-fire prompt>\n"
            "- <short check question or rapid-fire prompt>\n"
            "- <short check question or rapid-fire prompt>\n\n"
            "7. Closure (<time>)\n"
            "- Wrap-Up: <short recap>\n"
            "- Exit Ticket: <short exit prompt>\n\n"
            "Teaching Tips\n"
            "- <short tip>\n"
            "- <short tip>"
        )

        if not has_ncert_match:
            user_prompt += "\n\nLearn More\n- <one YouTube link only>"

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
                "has_ncert_match": has_ncert_match,
                "timing_map": timing_map,
            },
        )

    def _language_instruction(self, preferred_language: str) -> str:
        language = preferred_language.strip().casefold()
        if language == "hinglish":
            return (
                "Write the lesson body in simple Hinglish using Roman script only. "
                "Do not use Devanagari. Keep section headings in English. "
                "Use natural teacher-friendly Indian classroom wording with a light Hindi-English mix."
            )
        return "Write the lesson in clear, simple English."

    def _content_depth_instruction(self, subject: str) -> str:
        subject_key = subject.strip().casefold()
        if subject_key in {"physics", "science"}:
            return (
                "Keep the science correct and grade-appropriate. Use the real concept names, short cause-and-effect ideas, "
                "and one simple classroom demonstration or observation when useful."
            )
        if subject_key in {"mathematics", "maths", "math"}:
            return (
                "Include the real method, rule, or reasoning students need, plus at least one concrete example or practice move."
            )
        if subject_key in {"social science", "history", "geography", "political science", "economics", "civics"}:
            return (
                "Include the actual people, places, events, or concepts relevant to the topic in short classroom-ready bullets."
            )
        if subject_key in {"english", "hindi", "urdu", "language"}:
            return (
                "Include the real theme, vocabulary, comprehension focus, or language skill students should work on."
            )
        return "Keep the content specific to the requested topic and useful for direct classroom delivery."

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
