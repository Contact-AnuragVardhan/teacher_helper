from app.models.teacher_profile import TeacherProfile


class LessonGeneratorService:
    SAMPLE_NCERT_CONTEXT = (
        "Sample NCERT-aligned context: start from familiar examples, explain one core idea "
        "clearly, add one short activity, and end with quick questions to check understanding."
    )

    def generate(self, teacher: TeacherProfile, topic: str, duration_minutes: int) -> str:
        opening = max(3, duration_minutes // 6)
        main_teaching = max(10, duration_minutes // 2)
        activity = max(5, duration_minutes // 5)
        qa = max(4, duration_minutes // 8)
        used = opening + main_teaching + activity + qa
        closing = max(2, duration_minutes - used)

        lesson_title = f"{topic.strip().title()}"

        return (
            f"Lesson Title\n"
            f"{lesson_title}\n\n"
            f"Objective\n"
            f"Students will understand the basic idea of {topic.strip()} in {teacher.default_subject}.\n\n"
            f"Opening\n"
            f"({opening} min) Begin with a simple question linked to students' prior knowledge about {topic.strip()}.\n\n"
            f"Main Teaching\n"
            f"({main_teaching} min) Explain the key idea of {topic.strip()} step by step using clear examples for Grade {teacher.default_grade}.\n\n"
            f"Activity\n"
            f"({activity} min) Ask students to do one short classroom activity related to {topic.strip()} with a partner or notebook.\n\n"
            f"Q&A\n"
            f"({qa} min) Ask 2-3 quick checking questions and let students answer in their own words.\n\n"
            f"Closing\n"
            f"({closing} min) Summarize the lesson and connect it to the next class.\n\n"
            f"Teacher Notes\n"
            f"Language: {teacher.preferred_language}\n"
            f"Reference: {self.SAMPLE_NCERT_CONTEXT}"
        )
