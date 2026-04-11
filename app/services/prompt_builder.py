from dataclasses import dataclass, field

from app.services.lesson_generation_provider import PromptBundle
from app.core.logging import get_logger, log_event

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
                "Do not switch to another NCERT chapter or poem. Do not invent a Source section."
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
            f"Opening -> ({timing_map['opening']})\n"
            f"Main Teaching -> ({timing_map['main_teaching']})\n"
            f"Activity -> ({timing_map['activity']})\n"
            f"Q&A -> ({timing_map['qa']})\n"
            f"Closing -> ({timing_map['closing']})"
        )

        language_instruction = self._language_instruction(data.preferred_language)
        content_depth_instruction = self._content_depth_instruction(data.subject)

        system_prompt = (
            "You are a lesson planning assistant for Indian K-12 teachers. "
            "The task is Lesson Planning. "
            "Use simple, professional, teacher-friendly language. "
            "Return plain text only. "
            "Do not add markdown headings, emojis, or commentary outside the requested format. "
            "Keep the visible lesson sections exactly as: Lesson Title, Objective, Opening, Main Teaching, Activity, Q&A, Closing. "
            "Also include a short Lesson Planning summary block at the very top before Lesson Title. "
            "The sections Opening, Main Teaching, Activity, Q&A, and Closing MUST each start with a timing in parentheses "
            "on the first line of the section body, for example '(5 min)' or '(5–7 min)'. "
            "Do not omit timings. Do not add Source, Notes, Markdown headings, bullets before section titles, or extra sections. "
            "Every section must be topic-specific, classroom-usable, and content-rich for the exact requested topic. "
            "Do not write generic placeholders or meta-instructions such as 'Introduce the topic', 'Explain the concept', "
            "'Give students an activity', 'Ask a warm-up question', or 'Review the key learning'. "
            "Write the actual lesson content the teacher can directly use. "
            f"{language_instruction}"
        )

        match_instruction = (
            "- Build the lesson around the matched NCERT syllabus context above.\n"
            "- Keep the output classroom-ready and chapter-specific.\n"
            if has_ncert_match
            else
            "- No NCERT syllabus match was found. Build the lesson for the requested topic itself.\n"
            "- Do not substitute another poem, chapter, or textbook topic.\n"
            "- Do not add a Source section when no NCERT match exists.\n"
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
            "- Use the exact section headings only: Lesson Title, Objective, Opening, Main Teaching, Activity, Q&A, Closing.\n"
            "- Add this summary block at the top before Lesson Title:\n"
            "  Lesson Planning\n"
            f"  Topic - {data.topic}\n"
            f"  Grade/Class - {data.grade}\n"
            f"  Subject - {data.subject}\n"
            f"  Duration - {data.duration_minutes} min\n"
            "- No markdown like ## or **.\n"
            "- Do not add any other header above or below the summary block.\n"
            "- Each of these sections must begin with the timing in parentheses as the very first text in the section body: Opening, Main Teaching, Activity, Q&A, Closing.\n"
            "- Keep the outer lesson sections unchanged, but make the inside of each section concrete and usable.\n"
            "- Objective must be 3 to 5 separate outcome lines that mention specific knowledge or skills from this topic.\n"
            "- Opening should include a real hook, a real prior-knowledge connection, and a real lesson focus for this exact topic.\n"
            "- Main Teaching should use 5 to 7 numbered points with actual concept teaching, not generic pedagogy sentences.\n"
            "- Activity should be a concrete activity for this exact topic with clear student actions.\n"
            "- Q&A must contain exactly 4 short numbered questions on this exact topic, not generic reflection questions.\n"
            "- Closing should briefly recap the actual content taught and end with a relevant reflection.\n"
            f"- {content_depth_instruction}\n"
            f"- {language_instruction}\n"
            "- Avoid vague lines such as 'Explain important points', 'Use examples', 'Discuss the main idea', or 'Connect to real life'. Replace them with the actual points, examples, and questions.\n"
            f"- Use this time distribution exactly:\n{timing_block}\n\n"
            "Return in this exact plain-text shape:\n"
            "Lesson Planning\n"
            "Topic - <requested topic>\n"
            "Grade/Class - <grade>\n"
            "Subject - <subject>\n"
            "Duration - <duration> min\n\n"
            "Lesson Title\n"
            "<actual topic-specific title>\n\n"
            "Objective\n"
            "<3 to 5 actual topic-specific outcome lines>\n\n"
            "Opening\n"
            "(<time>)\n"
            "Hook: <actual hook for this topic>\n"
            "Connect: <actual prior-knowledge bridge for this topic>\n"
            "Focus: <actual lesson focus for this topic>\n\n"
            "Main Teaching\n"
            "(<time>)\n"
            "1. <actual topic-specific teaching point>\n"
            "2. <actual topic-specific teaching point>\n"
            "3. <actual topic-specific teaching point>\n"
            "4. <actual topic-specific teaching point>\n"
            "5. <actual topic-specific teaching point>\n\n"
            "Activity\n"
            "(<time>)\n"
            "Task: <actual task for this topic>\n"
            "Steps: <actual student steps for this topic>\n"
            "Share: <actual sharing/check-for-understanding step>\n\n"
            "Q&A\n"
            "(<time>)\n"
            "1. <actual topic-specific question>\n"
            "2. <actual topic-specific question>\n"
            "3. <actual topic-specific question>\n"
            "4. <actual topic-specific question>\n\n"
            "Closing\n"
            "(<time>)\n"
            "Recap: <actual recap of this topic>\n"
            "Reflection: <actual reflection tied to this topic>"
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
                "has_ncert_match": has_ncert_match,
                "timing_map": timing_map,
            },
        )

    def _language_instruction(self, preferred_language: str) -> str:
        language = preferred_language.strip().casefold()
        if language == "hinglish":
            return (
                "Write the lesson body in simple Hinglish using Roman script only. "
                "Do not use Devanagari. Keep the section headings exactly as requested in English. "
                "Use natural teacher-friendly Indian classroom wording with a light Hindi-English mix."
            )
        return "Write the lesson in clear, simple English."

    def _content_depth_instruction(self, subject: str) -> str:
        subject_key = subject.strip().casefold()
        if subject_key in {"physics", "science"}:
            return (
                "Use scientifically correct, grade-appropriate content. Include the actual concept names, "
                "simple cause-and-effect explanation, and at least one concrete example, observation, or demo idea."
            )
        if subject_key in {"mathematics", "maths", "math"}:
            return (
                "Include the actual method, worked idea, or reasoning steps students should learn, plus one concrete example."
            )
        if subject_key in {"social science", "history", "geography", "political science", "economics", "civics"}:
            return (
                "Include the actual people, places, events, or concepts relevant to the topic in age-appropriate detail."
            )
        if subject_key in {"english", "hindi", "urdu", "language"}:
            return (
                "Include the actual comprehension, vocabulary, language, or text-specific focus relevant to the topic."
            )
        return (
            "Include the actual facts, concepts, and examples needed to teach this topic well instead of generic teaching directions."
        )

    def _allocate_timings(self, duration_minutes: int) -> dict[str, str]:
        total = max(10, int(duration_minutes))

        opening = max(3, round(total * 0.125))
        main_teaching = max(10, round(total * 0.5))
        activity = max(4, round(total * 0.15))
        qa = max(4, round(total * 0.125))
        closing = total - (opening + main_teaching + activity + qa)

        if closing < 3:
            needed = 3 - closing
            reducible_order = ["main_teaching", "activity", "opening", "qa"]
            values = {
                "opening": opening,
                "main_teaching": main_teaching,
                "activity": activity,
                "qa": qa,
            }
            minimums = {
                "opening": 3,
                "main_teaching": 10,
                "activity": 4,
                "qa": 4,
            }
            for key in reducible_order:
                while needed > 0 and values[key] > minimums[key]:
                    values[key] -= 1
                    needed -= 1
                if needed == 0:
                    break
            opening = values["opening"]
            main_teaching = values["main_teaching"]
            activity = values["activity"]
            qa = values["qa"]
            closing = total - (opening + main_teaching + activity + qa)

        return {
            "opening": f"{opening} min",
            "main_teaching": f"{main_teaching} min",
            "activity": f"{activity} min",
            "qa": f"{qa} min",
            "closing": f"{closing} min",
        }
