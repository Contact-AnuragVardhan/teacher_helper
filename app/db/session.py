from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.logging import get_logger, log_event

settings = get_settings()
logger = get_logger(__name__)
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_is_sqlite else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator:
    db = SessionLocal()
    log_event(logger, "db_session_opened")
    try:
        yield db
    finally:
        db.close()
        log_event(logger, "db_session_closed")
