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

    def _main_menu_text(self) -> str:
        return (
            "Main Menu:\n"
            "1 → New Lesson\n"
            "2 → All Lessons\n"
            "3 → My Profile"
        )

    def _main_menu_with_prefix(self, prefix: str) -> str:
        return f"{prefix}\n\n{self._main_menu_text()}"

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

    def _new_lesson_grade_prompt(self) -> str:
        return "Please enter the grade/class for this lesson."

    def _new_lesson_subject_prompt(self) -> str:
        return "Please enter the subject for this lesson."

    def _main_menu_reply(self, prefix: str) -> ConversationReply:
        return self._reply(
            self._main_menu_with_prefix(prefix),
            ConversationState.MAIN_MENU,
            outbound={
                "type": "list",
                "header": "Teacher Helper",
                "body": "Choose an option",
                "button_text": "Open Menu",
                "section_title": "Main Menu",
                "footer": "Tap one option below",
                "rows": [
                    {"id": "menu_new_lesson", "title": "New Lesson"},
                    {"id": "menu_all_lessons", "title": "All Lessons"},
                    {"id": "menu_my_profile", "title": "My Profile"},
                ],
            },
        )

    def _save_menu_reply(self, lesson_text: str) -> ConversationReply:
        return self._reply(
            f"{messages.NEW_LESSON_SAVE_PROMPT_PREFIX}\n\n{lesson_text}\n\nDo you want to save this lesson?\n1 → Save Lesson\n2 → Cancel",
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

    def _all_lessons_interactive_reply(self, titles: list[str]) -> ConversationReply:
        rows = []
        for title in titles:
            item = {
                "id": title,
                "title": title[:24],
            }
            if len(title) > 24:
                item["description"] = title[:72]
            rows.append(item)

        reply_text = (
            "All Lessons:\n"
            f"{self._format_numbered_titles(titles)}\n\n"
            "Choose a lesson from the list below."
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

            titles = self.lesson_repo.list_titles_by_teacher(teacher.id)
            if not titles:
                self.session_repo.reset_for_main_menu(session)
                return self._main_menu_reply("You do not have any saved lessons yet.")

            session.current_state = ConversationState.RETRIEVE_LESSON_NAME.value
            self.session_repo.save(session)

            if len(titles) <= 10:
                return self._all_lessons_interactive_reply(titles)

            return self._all_lessons_fallback_reply(titles)

        if choice in {"3", "my profile", "menu_my_profile"}:
            session.current_state = ConversationState.PROFILE_NAME.value
            self.session_repo.clear_temp_profile(session)
            teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
            prompt = messages.PROFILE_UPDATED if teacher else messages.PROFILE_START
            return self._reply(prompt, ConversationState.PROFILE_NAME)

        return self._main_menu_reply(
            "I can help with creating a new lesson, viewing all saved lessons, or updating your profile. Please choose one of the options below."
        )

    def _handle_profile_name(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        if not text:
            return self._reply(messages.PROFILE_NAME_PROMPT, ConversationState.PROFILE_NAME)

        session.temp_profile_name = text
        session.current_state = ConversationState.PROFILE_GRADE.value
        self.session_repo.save(session)
        return self._reply(messages.PROFILE_GRADE_PROMPT, ConversationState.PROFILE_GRADE)

    def _handle_profile_grade(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        if not text:
            return self._reply(messages.PROFILE_GRADE_PROMPT, ConversationState.PROFILE_GRADE)

        grade_error = validate_profile_grade(text, self.settings)
        if grade_error:
            log_event(logger, "validation_failure", field="default_grade", value=text)
            return self._reply(
                f"{grade_error}\n{messages.PROFILE_GRADE_PROMPT}",
                ConversationState.PROFILE_GRADE,
            )

        session.temp_profile_grade = text.strip()
        session.current_state = ConversationState.PROFILE_SUBJECT.value
        self.session_repo.save(session)
        return self._reply(messages.PROFILE_SUBJECT_PROMPT, ConversationState.PROFILE_SUBJECT)

    def _handle_profile_subject(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        if not text:
            return self._reply(messages.PROFILE_SUBJECT_PROMPT, ConversationState.PROFILE_SUBJECT)

        subject_error = validate_profile_subject(
            text,
            session.temp_profile_grade or "",
            self.settings,
        )
        if subject_error:
            log_event(logger, "validation_failure", field="default_subject", value=text)
            return self._reply(
                f"{subject_error}\n{messages.PROFILE_SUBJECT_PROMPT}",
                ConversationState.PROFILE_SUBJECT,
            )

        session.temp_profile_subject = text.strip()
        session.current_state = ConversationState.PROFILE_LANGUAGE.value
        self.session_repo.save(session)
        return self._reply(messages.PROFILE_LANGUAGE_PROMPT, ConversationState.PROFILE_LANGUAGE)

    def _handle_profile_language(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        if normalize_choice(text) not in self.settings.supported_languages_casefold:
            log_event(logger, "validation_failure", field="preferred_language", value=text)
            return self._reply(messages.PROFILE_LANGUAGE_INVALID, ConversationState.PROFILE_LANGUAGE)

        self.teacher_repo.upsert(
            whatsapp_number=whatsapp_number,
            teacher_name=session.temp_profile_name or "",
            default_grade=session.temp_profile_grade or "",
            default_subject=session.temp_profile_subject or "",
            preferred_language=text.strip(),
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
        subject_error = validate_profile_subject(text, lesson_grade, self.settings)
        if subject_error:
            log_event(logger, "validation_failure", field="lesson_subject", value=text)
            return self._reply(
                f"{subject_error}\n{self._new_lesson_subject_prompt()}",
                ConversationState.NEW_LESSON_SUBJECT,
            )

        session.temp_profile_subject = text.strip()
        session.current_state = ConversationState.NEW_LESSON_DURATION.value
        self.session_repo.save(session)
        return self._reply(
            "Please enter class duration in minutes.",
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

        selected_title = None

        if text and text.isdigit():
            lesson_index = int(text)
            if 1 <= lesson_index <= len(titles):
                selected_title = titles[lesson_index - 1]
            else:
                return self._reply(
                    "Invalid lesson number. Please enter a valid lesson number from the list.\nSend 0 to return to the main menu.",
                    ConversationState.RETRIEVE_LESSON_NAME,
                )
        else:
            # For interactive list replies, the incoming text will be the title/id.
            exact_match = next((title for title in titles if title == text), None)
            if exact_match:
                selected_title = exact_match
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

        lesson = self.lesson_repo.get_by_teacher_and_name(teacher.id, selected_title)
        if not lesson:
            return self._reply(
                "I could not find that lesson. Please try again.\nSend 0 to return to the main menu.",
                ConversationState.RETRIEVE_LESSON_NAME,
            )

        self.session_repo.reset_for_main_menu(session)
        return self._reply(
            f"{lesson.lesson_text}\n\n{self._main_menu_text()}",
            ConversationState.MAIN_MENU,
            outbound={
                "type": "list",
                "header": "Teacher Helper",
                "body": "Choose what you want to do next.",
                "button_text": "Open Menu",
                "section_title": "Main Menu",
                "footer": "Tap one option below",
                "rows": [
                    {"id": "menu_new_lesson", "title": "New Lesson"},
                    {"id": "menu_all_lessons", "title": "All Lessons"},
                    {"id": "menu_my_profile", "title": "My Profile"},
                ],
            },
        )