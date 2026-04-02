from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger, log_event
from app.models.session_state import SessionState
from app.state_machine.states import ConversationState

logger = get_logger(__name__)


class SessionRepository:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()

    def get_or_create(self, whatsapp_number: str) -> tuple[SessionState, bool]:
        session = (
            self.db.query(SessionState)
            .filter(SessionState.whatsapp_number == whatsapp_number)
            .first()
        )
        if session is None:
            session = SessionState(
                whatsapp_number=whatsapp_number,
                current_state=ConversationState.MAIN_MENU.value,
            )
            self.db.add(session)
            self.db.commit()
            self.db.refresh(session)
            log_event(logger, "session_created", whatsapp_number=whatsapp_number)
            return session, False

        was_reset = False
        if self.is_stale(session):
            self.reset_for_main_menu(session)
            was_reset = True
            log_event(logger, "session_marked_stale", whatsapp_number=whatsapp_number)
        return session, was_reset

    def is_stale(self, session: SessionState) -> bool:
        timeout = timedelta(minutes=self.settings.session_timeout_minutes)
        return datetime.utcnow() - session.updated_at > timeout

    def save(self, session: SessionState) -> SessionState:
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        log_event(
            logger,
            "session_saved",
            whatsapp_number=session.whatsapp_number,
            current_state=session.current_state,
        )
        return session

    def touch(self, session: SessionState) -> SessionState:
        session.updated_at = datetime.utcnow()
        return self.save(session)

    def set_state(self, session: SessionState, state: ConversationState) -> SessionState:
        session.current_state = state.value
        return self.save(session)

    def clear_temp_lesson(self, session: SessionState) -> SessionState:
        session.temp_topic = None
        session.temp_duration_minutes = None
        session.temp_generated_lesson = None
        session.temp_lesson_name = None
        log_event(logger, "session_clear_temp_lesson", whatsapp_number=session.whatsapp_number)
        return self.save(session)

    def clear_temp_profile(self, session: SessionState) -> SessionState:
        session.temp_profile_name = None
        session.temp_profile_grade = None
        session.temp_profile_subject = None
        log_event(logger, "session_clear_temp_profile", whatsapp_number=session.whatsapp_number)
        return self.save(session)

    def reset_for_main_menu(self, session: SessionState) -> SessionState:
        session.current_state = ConversationState.MAIN_MENU.value
        session.temp_topic = None
        session.temp_duration_minutes = None
        session.temp_generated_lesson = None
        session.temp_lesson_name = None
        session.temp_profile_name = None
        session.temp_profile_grade = None
        session.temp_profile_subject = None
        session.updated_at = datetime.utcnow()
        log_event(logger, "session_reset_main_menu", whatsapp_number=session.whatsapp_number)
        return self.save(session)
