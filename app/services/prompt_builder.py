from dataclasses import dataclass, field

from app.services.lesson_generation_provider import PromptBundle


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
        context_block = "\n\n---\n\n".join(data.retrieved_snippets[:3]).strip()
        if not context_block:
            context_block = (
                "No NCERT syllabus row was retrieved. "
                "Use a safe, classroom-ready lesson structure and clearly stay generic."
            )

        timing_map = self._allocate_timings(data.duration_minutes)
        timing_block = (
            f"Opening -> ({timing_map['opening']})\n"
            f"Main Teaching -> ({timing_map['main_teaching']})\n"
            f"Activity -> ({timing_map['activity']})\n"
            f"Q&A -> ({timing_map['qa']})\n"
            f"Closing -> ({timing_map['closing']})"
        )

        system_prompt = (
            "You are a lesson planning assistant for Indian K-12 teachers. "
            "Stay aligned to the provided NCERT syllabus context. "
            "Use simple, professional, teacher-friendly language. "
            "Return plain text only. "
            "Return exactly these sections and no extra commentary: "
            "Lesson Title, Objective, Opening, Main Teaching, Activity, Q&A, Closing. "
            "The sections Opening, Main Teaching, Activity, Q&A, and Closing MUST each start with a timing in parentheses "
            "on the first line of the section body, for example '(5 min)' or '(5–7 min)'. "
            "Do not omit timings. Do not add Source, Notes, Markdown headings, bullets before section titles, or extra sections."
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
            "- Keep the output concise, classroom-ready, and chapter-specific.\n"
            "- Use the exact section headings only.\n"
            "- No markdown like ## or **.\n"
            "- Do not add Teacher Notes, References, Source, or any extra headings.\n"
            "- Each of these sections must begin with the timing in parentheses as the very first text in the section body: Opening, Main Teaching, Activity, Q&A, Closing.\n"
            f"- Use this time distribution exactly:\n{timing_block}\n\n"
            "Return in this exact plain-text shape:\n"
            "Lesson Title\n"
            "<title>\n\n"
            "Objective\n"
            "<one concise objective paragraph>\n\n"
            "Opening\n"
            "(<time>)\n"
            "<opening text>\n\n"
            "Main Teaching\n"
            "(<time>)\n"
            "<short teaching points>\n\n"
            "Activity\n"
            "(<time>)\n"
            "<activity text>\n\n"
            "Q&A\n"
            "(<time>)\n"
            "<4 short questions>\n\n"
            "Closing\n"
            "(<time>) <closing text>"
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
                "timing_map": timing_map,
            },
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