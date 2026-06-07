from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.core.logging import get_logger, log_event

logger = get_logger(__name__)


_RUNTIME_COLUMNS: dict[str, dict[str, str]] = {
    "teacher_profile": {
        "school_name": "VARCHAR(255)",
    },
    "session_state": {
        "temp_profile_school": "VARCHAR(255)",
        "temp_content_document_id": "VARCHAR(80)",
        "temp_content_chapter_id": "VARCHAR(80)",
        "temp_content_subsection_id": "VARCHAR(80)",
        "temp_lesson_day_number": "INTEGER",
        "temp_lesson_day_title": "VARCHAR(100)",
        "temp_lesson_book_title": "VARCHAR(255)",
        "temp_lesson_chapter_title": "VARCHAR(255)",
        "temp_lesson_section_title": "VARCHAR(255)",
        "temp_lesson_subsection_number": "VARCHAR(80)",
        "temp_lesson_subsection_title": "VARCHAR(255)",
        "temp_lesson_book_pages": "VARCHAR(100)",
        "temp_lesson_pdf_start_page": "INTEGER",
        "temp_lesson_pdf_end_page": "INTEGER",
        "temp_lesson_printed_start_page": "INTEGER",
        "temp_lesson_printed_end_page": "INTEGER",
        "temp_lesson_document_key": "VARCHAR(255)",
        "temp_lesson_school_name": "VARCHAR(255)",
        "temp_lesson_summary": "TEXT",
    },
    "lesson_plan": {
        "document_id": "VARCHAR(80)",
        "document_key": "VARCHAR(255)",
        "book_title": "VARCHAR(255)",
        "school_name": "VARCHAR(255)",
        "chapter_id": "VARCHAR(80)",
        "subsection_id": "VARCHAR(80)",
        "chapter_title": "VARCHAR(255)",
        "section_title": "VARCHAR(255)",
        "subsection_number": "VARCHAR(80)",
        "subsection_title": "VARCHAR(255)",
        "day_number": "INTEGER",
        "day_title": "VARCHAR(100)",
        "book_pages": "VARCHAR(100)",
        "pdf_start_page": "INTEGER",
        "pdf_end_page": "INTEGER",
        "printed_start_page": "INTEGER",
        "printed_end_page": "INTEGER",
        "resource_profile": "VARCHAR(100)",
        "format_profile": "VARCHAR(100)",
    },
}


def ensure_runtime_columns(engine: Engine) -> None:
    """Add lightweight backward-compatible columns for already-created app DB tables.

    SQLAlchemy create_all() creates new tables with the latest model columns, but it does not
    alter existing production tables. This keeps older Teacher Helper deployments compatible
    without requiring Alembic for these small additive changes.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if not existing_tables:
        return

    with engine.begin() as conn:
        for table_name, columns in _RUNTIME_COLUMNS.items():
            if table_name not in existing_tables:
                continue
            existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, ddl_type in columns.items():
                if column_name in existing_columns:
                    continue
                try:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl_type}"))
                    log_event(logger, "runtime_column_added", table=table_name, column=column_name)
                except SQLAlchemyError as exc:  # pragma: no cover - defensive startup logging.
                    log_event(logger, "runtime_column_add_failed", table=table_name, column=column_name, error=str(exc))
