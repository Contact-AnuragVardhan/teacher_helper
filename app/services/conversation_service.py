from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core import messages
from app.core.config import get_settings
from app.core.logging import get_logger, log_event
from app.repositories.lesson_repository import LessonRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.teacher_repository import TeacherRepository
from app.services.lesson_generator import LessonGeneratorService
from app.state_machine.states import ConversationState
from app.utils.profile_validation import validate_profile_grade, validate_profile_subject
from app.utils.subject_normalization import normalize_subject
from app.utils.text import clean_text, normalize_choice

logger = get_logger(__name__)


@dataclass
class ConversationReply:
    reply: str
    current_state: str
    outbound: dict | None = None


class ConversationService:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
        self.teacher_repo = TeacherRepository(db)
        self.lesson_repo = LessonRepository(db)
        self.session_repo = SessionRepository(db)
        self.lesson_generator = LessonGeneratorService(db)

    def handle_message(self, whatsapp_number: str, incoming_text: str) -> ConversationReply:
        session, was_reset = self.session_repo.get_or_create(whatsapp_number)
        self.session_repo.touch(session)
        if was_reset:
            log_event(logger, "session_stale_reset", whatsapp_number=whatsapp_number)

        state = ConversationState(session.current_state)
        text = clean_text(incoming_text)
        log_event(logger, "conversation_inbound", whatsapp_number=whatsapp_number, state=state.value, body=text)

        handler_map = {
            ConversationState.MAIN_MENU: self._handle_main_menu,
            ConversationState.PROFILE_NAME: self._handle_profile_name,
            ConversationState.PROFILE_GRADE: self._handle_profile_grade,
            ConversationState.PROFILE_SUBJECT: self._handle_profile_subject,
            ConversationState.PROFILE_LANGUAGE: self._handle_profile_language,
            ConversationState.NEW_LESSON_TOPIC: self._handle_new_lesson_topic,
            ConversationState.NEW_LESSON_GRADE: self._handle_new_lesson_grade,
            ConversationState.NEW_LESSON_SUBJECT: self._handle_new_lesson_subject,
            ConversationState.NEW_LESSON_DURATION: self._handle_new_lesson_duration,
            ConversationState.NEW_LESSON_CONFIRM_SAVE: self._handle_new_lesson_confirm_save,
            ConversationState.NEW_LESSON_NAME: self._handle_new_lesson_name,
            ConversationState.RETRIEVE_LESSON_NAME: self._handle_retrieve_lesson_name,
        }

        result = handler_map[state](session, whatsapp_number, text)
        log_event(
            logger,
            "conversation_transition",
            whatsapp_number=whatsapp_number,
            from_state=state.value,
            to_state=result.current_state,
        )
        return result

    def _reply(
        self,
        reply: str,
        state: ConversationState,
        outbound: dict | None = None,
    ) -> ConversationReply:
        return ConversationReply(reply=reply, current_state=state.value, outbound=outbound)

    def _main_menu_prompt(self, prefix: str) -> str:
        prompt = "Please tap one option below."
        clean_prefix = (prefix or "").strip()
        if not clean_prefix:
            return prompt
        return f"{clean_prefix}\n\n{prompt}"

    def _format_numbered_titles(self, titles: list[str]) -> str:
        return "\n".join(f"{index}. {title}" for index, title in enumerate(titles, start=1))

    def _is_greeting(self, choice: str) -> bool:
        return choice in {
            "hi",
            "hello",
            "hey",
            "hii",
            "hiii",
            "helo",
            "hola",
            "good morning",
            "good afternoon",
            "good evening",
            "start",
        }

    def _is_keep_value(self, text: str) -> bool:
        return normalize_choice(text) in {"same", "skip", "keep", "current"}

    def _language_options_text(self) -> str:
        languages = self.settings.supported_languages_list or ["English"]
        if len(languages) == 1:
            return languages[0]
        return ", ".join(languages)

    def _new_lesson_grade_prompt(self) -> str:
        return "Please enter the grade/class for this lesson. Example: 1, 2, 3"

    def _new_lesson_subject_prompt(self) -> str:
        return "Please enter the subject for this lesson. Example: English"

    def _profile_language_prompt(self) -> str:
        return f"Please enter preferred language. Example: {self._language_options_text()}"

    def _profile_update_summary(self, teacher) -> str:
        return (
            "Current profile:\n"
            f"Name: {teacher.teacher_name}\n"
            f"Grade: {teacher.default_grade}\n"
            f"Subject: {teacher.default_subject}\n"
            f"Language: {teacher.preferred_language}"
        )

    def _profile_name_edit_prompt(self, teacher) -> str:
        return (
            f"{messages.PROFILE_UPDATED}\n\n"
            f"{self._profile_update_summary(teacher)}\n\n"
            "Reply with your name, or send 'same' to keep the current value."
        )

    def _profile_grade_edit_prompt(self, teacher) -> str:
        return (
            f"Current grade/class: {teacher.default_grade}\n"
            "Reply with the new grade/class, or send 'same' to keep it. Example: 1, 2, 3"
        )

    def _profile_subject_edit_prompt(self, teacher) -> str:
        return (
            f"Current subject: {teacher.default_subject}\n"
            "Reply with the new subject, or send 'same' to keep it. Example: English"
        )

    def _profile_language_edit_prompt(self, teacher) -> str:
        return (
            f"Current language: {teacher.preferred_language}\n"
            f"Reply with the new language, or send 'same' to keep it. Example: {self._language_options_text()}"
        )

    def _main_menu_outbound(self) -> dict:
        return {
            "type": "buttons",
            "header": "Teacher Helper",
            "body": "Choose an option",
            "footer": "Tap one option below",
            "buttons": [
                {"id": "menu_new_lesson", "title": "New Lesson"},
                {"id": "menu_all_lessons", "title": "All Lessons"},
                {"id": "menu_my_profile", "title": "My Profile"},
            ],
        }

    def _main_menu_reply(self, prefix: str) -> ConversationReply:
        return self._reply(
            self._main_menu_prompt(prefix),
            ConversationState.MAIN_MENU,
            outbound=self._main_menu_outbound(),
        )

    def _save_menu_reply(self, lesson_text: str) -> ConversationReply:
        return self._reply(
            f"{messages.NEW_LESSON_SAVE_PROMPT_PREFIX}\n\n{lesson_text}",
            ConversationState.NEW_LESSON_CONFIRM_SAVE,
            outbound={
                "type": "buttons",
                "header": "Teacher Helper",
                "body": "Do you want to save this lesson?",
                "footer": "Choose one option",
                "buttons": [
                    {"id": "save_lesson", "title": "Save Lesson"},
                    {"id": "cancel_lesson", "title": "Cancel"},
                ],
            },
        )

    def _all_lessons_interactive_reply(self, lesson_summaries: list[tuple[int, str]]) -> ConversationReply:
        rows = []
        for lesson_id, title in lesson_summaries:
            item = {
                "id": f"lesson_id:{lesson_id}",
                "title": title[:24],
            }
            if len(title) > 24:
                item["description"] = title[:72]
            rows.append(item)

        reply_text = (
            "All Lessons:\n"
            "Please choose a lesson from the list below."
        )

        return self._reply(
            reply_text,
            ConversationState.RETRIEVE_LESSON_NAME,
            outbound={
                "type": "list",
                "header": "Saved Lessons",
                "body": "Choose a lesson to open.",
                "button_text": "View Lessons",
                "section_title": "Your Lessons",
                "footer": "Tap one lesson below.",
                "rows": rows,
            },
        )

    def _all_lessons_fallback_reply(self, titles: list[str]) -> ConversationReply:
        reply_text = (
            "All Lessons:\n"
            f"{self._format_numbered_titles(titles)}\n\n"
            "Reply with the lesson number to open it.\n"
            "Send 0 to return to the main menu."
        )
        return self._reply(reply_text, ConversationState.RETRIEVE_LESSON_NAME)

    def _handle_main_menu(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        choice = normalize_choice(text)

        if not choice or self._is_greeting(choice):
            return self._main_menu_reply(
                "Hello! Welcome to Teacher Helper. I can help you create, save, and view lesson plans."
            )

        if choice in {"1", "new lesson", "menu_new_lesson"}:
            teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
            if not teacher:
                session.current_state = ConversationState.PROFILE_NAME.value
                self.session_repo.clear_temp_profile(session)
                return self._reply(messages.NEW_LESSON_WITHOUT_PROFILE, ConversationState.PROFILE_NAME)

            session.temp_profile_grade = None
            session.temp_profile_subject = None
            session.current_state = ConversationState.NEW_LESSON_TOPIC.value
            self.session_repo.save(session)
            return self._reply(messages.NEW_LESSON_TOPIC_PROMPT, ConversationState.NEW_LESSON_TOPIC)

        if choice in {"2", "all lessons", "menu_all_lessons"}:
            teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
            if not teacher:
                session.current_state = ConversationState.PROFILE_NAME.value
                self.session_repo.clear_temp_profile(session)
                return self._reply(messages.NEW_LESSON_WITHOUT_PROFILE, ConversationState.PROFILE_NAME)

            lesson_summaries = self.lesson_repo.list_summaries_by_teacher(teacher.id)
            titles = [title for _, title in lesson_summaries]
            if not titles:
                self.session_repo.reset_for_main_menu(session)
                return self._main_menu_reply("You do not have any saved lessons yet.")

            session.current_state = ConversationState.RETRIEVE_LESSON_NAME.value
            self.session_repo.save(session)

            if len(titles) <= 10:
                return self._all_lessons_interactive_reply(lesson_summaries)

            return self._all_lessons_fallback_reply(titles)

        if choice in {"3", "my profile", "menu_my_profile"}:
            teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
            self.session_repo.clear_temp_profile(session)
            session.current_state = ConversationState.PROFILE_NAME.value

            if teacher:
                session.temp_profile_name = teacher.teacher_name
                session.temp_profile_grade = teacher.default_grade
                session.temp_profile_subject = teacher.default_subject
                self.session_repo.save(session)
                return self._reply(self._profile_name_edit_prompt(teacher), ConversationState.PROFILE_NAME)

            self.session_repo.save(session)
            return self._reply(messages.PROFILE_START, ConversationState.PROFILE_NAME)

        return self._main_menu_reply(
            "I can help with creating a new lesson, viewing all saved lessons, or updating your profile. Please choose one of the options below."
        )

    def _handle_profile_name(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        if not text:
            if teacher:
                return self._reply(self._profile_name_edit_prompt(teacher), ConversationState.PROFILE_NAME)
            return self._reply(messages.PROFILE_NAME_PROMPT, ConversationState.PROFILE_NAME)

        if teacher and self._is_keep_value(text):
            session.temp_profile_name = teacher.teacher_name
        else:
            session.temp_profile_name = text

        session.current_state = ConversationState.PROFILE_GRADE.value
        self.session_repo.save(session)

        if teacher:
            return self._reply(self._profile_grade_edit_prompt(teacher), ConversationState.PROFILE_GRADE)
        return self._reply(messages.PROFILE_GRADE_PROMPT, ConversationState.PROFILE_GRADE)

    def _handle_profile_grade(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        if not text:
            if teacher:
                return self._reply(self._profile_grade_edit_prompt(teacher), ConversationState.PROFILE_GRADE)
            return self._reply(messages.PROFILE_GRADE_PROMPT, ConversationState.PROFILE_GRADE)

        if teacher and self._is_keep_value(text):
            grade_value = teacher.default_grade
        else:
            grade_value = text.strip()
            grade_error = validate_profile_grade(grade_value, self.settings)
            if grade_error:
                log_event(logger, "validation_failure", field="default_grade", value=text)
                prompt = self._profile_grade_edit_prompt(teacher) if teacher else messages.PROFILE_GRADE_PROMPT
                return self._reply(
                    f"{grade_error}\n{prompt}",
                    ConversationState.PROFILE_GRADE,
                )

        session.temp_profile_grade = grade_value
        session.current_state = ConversationState.PROFILE_SUBJECT.value
        self.session_repo.save(session)

        if teacher:
            return self._reply(self._profile_subject_edit_prompt(teacher), ConversationState.PROFILE_SUBJECT)
        return self._reply(messages.PROFILE_SUBJECT_PROMPT, ConversationState.PROFILE_SUBJECT)

    def _handle_profile_subject(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        if not text:
            if teacher:
                return self._reply(self._profile_subject_edit_prompt(teacher), ConversationState.PROFILE_SUBJECT)
            return self._reply(messages.PROFILE_SUBJECT_PROMPT, ConversationState.PROFILE_SUBJECT)

        if teacher and self._is_keep_value(text):
            subject_value = teacher.default_subject
        else:
            subject_value = normalize_subject(text)
            subject_error = validate_profile_subject(
                subject_value,
                session.temp_profile_grade or "",
                self.settings,
            )
            if subject_error:
                log_event(logger, "validation_failure", field="default_subject", value=text)
                prompt = self._profile_subject_edit_prompt(teacher) if teacher else messages.PROFILE_SUBJECT_PROMPT
                return self._reply(
                    f"{subject_error}\n{prompt}",
                    ConversationState.PROFILE_SUBJECT,
                )

        session.temp_profile_subject = subject_value
        session.current_state = ConversationState.PROFILE_LANGUAGE.value
        self.session_repo.save(session)

        if teacher:
            return self._reply(self._profile_language_edit_prompt(teacher), ConversationState.PROFILE_LANGUAGE)
        return self._reply(self._profile_language_prompt(), ConversationState.PROFILE_LANGUAGE)

    def _handle_profile_language(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        if not text:
            if teacher:
                return self._reply(self._profile_language_edit_prompt(teacher), ConversationState.PROFILE_LANGUAGE)
            return self._reply(self._profile_language_prompt(), ConversationState.PROFILE_LANGUAGE)

        if teacher and self._is_keep_value(text):
            language_value = teacher.preferred_language
        else:
            language_value = text.strip()
            if normalize_choice(language_value) not in self.settings.supported_languages_casefold:
                log_event(logger, "validation_failure", field="preferred_language", value=text)
                prompt = self._profile_language_edit_prompt(teacher) if teacher else self._profile_language_prompt()
                return self._reply(
                    f"{messages.PROFILE_LANGUAGE_INVALID}\n{prompt}",
                    ConversationState.PROFILE_LANGUAGE,
                )

        self.teacher_repo.upsert(
            whatsapp_number=whatsapp_number,
            teacher_name=session.temp_profile_name or "",
            default_grade=session.temp_profile_grade or "",
            default_subject=session.temp_profile_subject or "",
            preferred_language=language_value,
        )
        self.session_repo.reset_for_main_menu(session)
        return self._main_menu_reply(messages.PROFILE_SAVED)

    def _handle_new_lesson_topic(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        if not text:
            log_event(logger, "validation_failure", field="topic", value=text)
            return self._reply(messages.NEW_LESSON_TOPIC_INVALID, ConversationState.NEW_LESSON_TOPIC)

        session.temp_topic = text
        session.current_state = ConversationState.NEW_LESSON_GRADE.value
        self.session_repo.save(session)
        return self._reply(self._new_lesson_grade_prompt(), ConversationState.NEW_LESSON_GRADE)

    def _handle_new_lesson_grade(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        if not text:
            return self._reply(self._new_lesson_grade_prompt(), ConversationState.NEW_LESSON_GRADE)

        grade_error = validate_profile_grade(text, self.settings)
        if grade_error:
            log_event(logger, "validation_failure", field="lesson_grade", value=text)
            return self._reply(
                f"{grade_error}\n{self._new_lesson_grade_prompt()}",
                ConversationState.NEW_LESSON_GRADE,
            )

        session.temp_profile_grade = text.strip()
        session.current_state = ConversationState.NEW_LESSON_SUBJECT.value
        self.session_repo.save(session)
        return self._reply(self._new_lesson_subject_prompt(), ConversationState.NEW_LESSON_SUBJECT)

    def _handle_new_lesson_subject(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        if not text:
            return self._reply(self._new_lesson_subject_prompt(), ConversationState.NEW_LESSON_SUBJECT)

        lesson_grade = session.temp_profile_grade or ""
        normalized_subject = normalize_subject(text)
        subject_error = validate_profile_subject(normalized_subject, lesson_grade, self.settings)
        if subject_error:
            log_event(logger, "validation_failure", field="lesson_subject", value=text)
            return self._reply(
                f"{subject_error}\n{self._new_lesson_subject_prompt()}",
                ConversationState.NEW_LESSON_SUBJECT,
            )

        session.temp_profile_subject = normalized_subject
        session.current_state = ConversationState.NEW_LESSON_DURATION.value
        self.session_repo.save(session)
        return self._reply(
            "Please enter class duration in minutes. Example: 35",
            ConversationState.NEW_LESSON_DURATION,
        )

    def _handle_new_lesson_duration(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        try:
            duration = int(text)
            if duration <= 0:
                raise ValueError
        except (TypeError, ValueError):
            log_event(logger, "validation_failure", field="duration_minutes", value=text)
            return self._reply(messages.INVALID_DURATION, ConversationState.NEW_LESSON_DURATION)

        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        if not teacher:
            session.current_state = ConversationState.PROFILE_NAME.value
            self.session_repo.save(session)
            return self._reply(messages.NEW_LESSON_WITHOUT_PROFILE, ConversationState.PROFILE_NAME)

        lesson_grade = (session.temp_profile_grade or "").strip() or teacher.default_grade
        lesson_subject = (session.temp_profile_subject or "").strip() or teacher.default_subject

        generation_result = self.lesson_generator.generate(
            teacher=teacher,
            topic=session.temp_topic or "",
            duration_minutes=duration,
            grade=lesson_grade,
            subject=lesson_subject,
        )
        session.temp_duration_minutes = duration
        session.temp_generated_lesson = generation_result.lesson_text
        session.current_state = ConversationState.NEW_LESSON_CONFIRM_SAVE.value
        self.session_repo.save(session)

        return self._save_menu_reply(generation_result.lesson_text)

    def _handle_new_lesson_confirm_save(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        choice = normalize_choice(text)

        if choice in {"1", "save lesson", "save_lesson"}:
            session.current_state = ConversationState.NEW_LESSON_NAME.value
            self.session_repo.save(session)
            return self._reply(messages.NEW_LESSON_NAME_PROMPT, ConversationState.NEW_LESSON_NAME)

        if choice in {"2", "cancel", "cancel_lesson"}:
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply("Lesson was not saved.")

        return self._reply(
            "Please choose one option:\n1 → Save Lesson\n2 → Cancel",
            ConversationState.NEW_LESSON_CONFIRM_SAVE,
            outbound={
                "type": "buttons",
                "header": "Teacher Helper",
                "body": "Do you want to save this lesson?",
                "footer": "Choose one option",
                "buttons": [
                    {"id": "save_lesson", "title": "Save Lesson"},
                    {"id": "cancel_lesson", "title": "Cancel"},
                ],
            },
        )

    def _handle_new_lesson_name(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        if not text:
            log_event(logger, "validation_failure", field="lesson_name", value=text)
            return self._reply(messages.NEW_LESSON_NAME_INVALID, ConversationState.NEW_LESSON_NAME)

        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        if not teacher:
            session.current_state = ConversationState.PROFILE_NAME.value
            self.session_repo.save(session)
            return self._reply(messages.NEW_LESSON_WITHOUT_PROFILE, ConversationState.PROFILE_NAME)

        lesson_grade = (session.temp_profile_grade or "").strip() or teacher.default_grade
        lesson_subject = (session.temp_profile_subject or "").strip() or teacher.default_subject

        lesson = self.lesson_repo.create_or_update_by_policy(
            teacher_id=teacher.id,
            lesson_name=text,
            topic=session.temp_topic or "",
            grade=lesson_grade,
            subject=lesson_subject,
            duration_minutes=session.temp_duration_minutes or 0,
            lesson_text=session.temp_generated_lesson or "",
        )
        if lesson is None:
            return self._reply(messages.DUPLICATE_LESSON_NAME, ConversationState.NEW_LESSON_NAME)

        self.session_repo.reset_for_main_menu(session)
        return self._main_menu_reply(messages.LESSON_SAVED)

    def _handle_retrieve_lesson_name(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        choice = normalize_choice(text)

        if choice in {"0", "menu", "main menu", "back"}:
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply("Back to main menu.")

        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        if not teacher:
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply("Please create your profile first.")

        titles = self.lesson_repo.list_titles_by_teacher(teacher.id)
        if not titles:
            self.session_repo.reset_for_main_menu(session)
            return self._main_menu_reply("You do not have any saved lessons yet.")

        lesson = None

        if choice.startswith("lesson_id:"):
            raw_lesson_id = choice.split(":", 1)[1].strip()
            if raw_lesson_id.isdigit():
                lesson = self.lesson_repo.get_by_teacher_and_id(teacher.id, int(raw_lesson_id))
        elif text and text.isdigit():
            lesson_index = int(text)
            if 1 <= lesson_index <= len(titles):
                selected_title = titles[lesson_index - 1]
                lesson = self.lesson_repo.get_by_teacher_and_name(teacher.id, selected_title)
            else:
                return self._reply(
                    "Invalid lesson number. Please enter a valid lesson number from the list.\nSend 0 to return to the main menu.",
                    ConversationState.RETRIEVE_LESSON_NAME,
                )
        else:
            exact_match = next((title for title in titles if title.casefold() == choice), None)
            if exact_match:
                lesson = self.lesson_repo.get_by_teacher_and_name(teacher.id, exact_match)
            else:
                prefix_matches = [title for title in titles if title.casefold().startswith(choice)]
                if len(prefix_matches) == 1:
                    lesson = self.lesson_repo.get_by_teacher_and_name(teacher.id, prefix_matches[0])
                else:
                    if len(titles) <= 10:
                        return self._reply(
                            "Please choose a lesson from the WhatsApp list, or send 0 to return to the main menu.",
                            ConversationState.RETRIEVE_LESSON_NAME,
                        )
                    return self._reply(
                        "Please enter the lesson number from the list.\nSend 0 to return to the main menu.",
                        ConversationState.RETRIEVE_LESSON_NAME,
                    )

        if not lesson:
            return self._reply(
                "I could not find that lesson. Please try again.\nSend 0 to return to the main menu.",
                ConversationState.RETRIEVE_LESSON_NAME,
            )

        self.session_repo.reset_for_main_menu(session)
        return self._reply(
            f"{lesson.lesson_text}\n\nPlease tap one option below.",
            ConversationState.MAIN_MENU,
            outbound=self._main_menu_outbound(),
        )
