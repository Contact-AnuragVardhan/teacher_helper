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
from app.utils.text import clean_text, normalize_choice

logger = get_logger(__name__)


@dataclass
class ConversationReply:
    reply: str
    current_state: str


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

    def _reply(self, reply: str, state: ConversationState) -> ConversationReply:
        return ConversationReply(reply=reply, current_state=state.value)

    def _main_menu_with_prefix(self, prefix: str) -> str:
        return f"{prefix}\n\n{messages.MAIN_MENU}"

    def _handle_main_menu(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        choice = normalize_choice(text)

        if choice in {"1", "new lesson"}:
            teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
            if not teacher:
                session.current_state = ConversationState.PROFILE_NAME.value
                self.session_repo.clear_temp_profile(session)
                return self._reply(messages.NEW_LESSON_WITHOUT_PROFILE, ConversationState.PROFILE_NAME)

            session.current_state = ConversationState.NEW_LESSON_TOPIC.value
            self.session_repo.save(session)
            return self._reply(messages.NEW_LESSON_TOPIC_PROMPT, ConversationState.NEW_LESSON_TOPIC)

        if choice in {"2", "my lessons"}:
            session.current_state = ConversationState.RETRIEVE_LESSON_NAME.value
            self.session_repo.save(session)
            return self._reply(
                messages.RETRIEVE_LESSON_NAME_PROMPT,
                ConversationState.RETRIEVE_LESSON_NAME,
            )

        if choice in {"3", "my profile"}:
            session.current_state = ConversationState.PROFILE_NAME.value
            self.session_repo.clear_temp_profile(session)
            teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
            prompt = messages.PROFILE_UPDATED if teacher else messages.PROFILE_START
            return self._reply(prompt, ConversationState.PROFILE_NAME)

        return self._reply(messages.INVALID_MAIN_MENU, ConversationState.MAIN_MENU)

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

        session.temp_profile_grade = text
        session.current_state = ConversationState.PROFILE_SUBJECT.value
        self.session_repo.save(session)
        return self._reply(messages.PROFILE_SUBJECT_PROMPT, ConversationState.PROFILE_SUBJECT)

    def _handle_profile_subject(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        if not text:
            return self._reply(messages.PROFILE_SUBJECT_PROMPT, ConversationState.PROFILE_SUBJECT)

        session.temp_profile_subject = text
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
        return self._reply(
            self._main_menu_with_prefix(messages.PROFILE_SAVED),
            ConversationState.MAIN_MENU,
        )

    def _handle_new_lesson_topic(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        if not text:
            log_event(logger, "validation_failure", field="topic", value=text)
            return self._reply(messages.NEW_LESSON_TOPIC_INVALID, ConversationState.NEW_LESSON_TOPIC)

        session.temp_topic = text
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

        generation_result = self.lesson_generator.generate(
            teacher=teacher,
            topic=session.temp_topic or "",
            duration_minutes=duration,
        )
        session.temp_duration_minutes = duration
        session.temp_generated_lesson = generation_result.lesson_text
        session.current_state = ConversationState.NEW_LESSON_CONFIRM_SAVE.value
        self.session_repo.save(session)

        reply = (
            f"{messages.NEW_LESSON_SAVE_PROMPT_PREFIX}\n\n"
            f"{generation_result.lesson_text}\n\n"
            f"{messages.SAVE_MENU}"
        )
        return self._reply(reply, ConversationState.NEW_LESSON_CONFIRM_SAVE)

    def _handle_new_lesson_confirm_save(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        choice = normalize_choice(text)
        if choice in {"1", "save lesson"}:
            session.current_state = ConversationState.NEW_LESSON_NAME.value
            self.session_repo.save(session)
            return self._reply(messages.NEW_LESSON_NAME_PROMPT, ConversationState.NEW_LESSON_NAME)

        if choice in {"2", "cancel"}:
            self.session_repo.reset_for_main_menu(session)
            return self._reply(
                self._main_menu_with_prefix(messages.LESSON_CANCELLED),
                ConversationState.MAIN_MENU,
            )

        return self._reply(messages.INVALID_SAVE_MENU, ConversationState.NEW_LESSON_CONFIRM_SAVE)

    def _handle_new_lesson_name(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        if not text:
            log_event(logger, "validation_failure", field="lesson_name", value=text)
            return self._reply(messages.NEW_LESSON_NAME_INVALID, ConversationState.NEW_LESSON_NAME)

        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        if not teacher:
            session.current_state = ConversationState.PROFILE_NAME.value
            self.session_repo.save(session)
            return self._reply(messages.NEW_LESSON_WITHOUT_PROFILE, ConversationState.PROFILE_NAME)

        lesson = self.lesson_repo.create_or_update_by_policy(
            teacher_id=teacher.id,
            lesson_name=text,
            topic=session.temp_topic or "",
            grade=teacher.default_grade,
            subject=teacher.default_subject,
            duration_minutes=session.temp_duration_minutes or 0,
            lesson_text=session.temp_generated_lesson or "",
        )
        if lesson is None:
            return self._reply(messages.DUPLICATE_LESSON_NAME, ConversationState.NEW_LESSON_NAME)

        self.session_repo.reset_for_main_menu(session)
        return self._reply(
            self._main_menu_with_prefix(messages.LESSON_SAVED),
            ConversationState.MAIN_MENU,
        )

    def _handle_retrieve_lesson_name(self, session, whatsapp_number: str, text: str) -> ConversationReply:
        choice = normalize_choice(text)
        if choice in {"0", "menu", "main menu", "back"}:
            self.session_repo.reset_for_main_menu(session)
            return self._reply(messages.MAIN_MENU, ConversationState.MAIN_MENU)

        if not text:
            return self._reply(
                messages.RETRIEVE_LESSON_NAME_INVALID,
                ConversationState.RETRIEVE_LESSON_NAME,
            )

        teacher = self.teacher_repo.get_by_whatsapp_number(whatsapp_number)
        if not teacher:
            self.session_repo.reset_for_main_menu(session)
            return self._reply(
                self._main_menu_with_prefix("Please create your profile first."),
                ConversationState.MAIN_MENU,
            )

        lesson = self.lesson_repo.get_by_teacher_and_name(teacher.id, text)
        if not lesson:
            return self._reply(
                f"{messages.LESSON_NOT_FOUND}\n{messages.LESSON_LOOKUP_EXIT_HINT}",
                ConversationState.RETRIEVE_LESSON_NAME,
            )

        self.session_repo.reset_for_main_menu(session)
        reply = f"{lesson.lesson_text}\n\n{messages.MAIN_MENU}"
        return self._reply(reply, ConversationState.MAIN_MENU)
