import json
from pathlib import Path

from app.models.ncert_content import NcertContent
from app.models.teacher_profile import TeacherProfile
from app.services.lesson_generation_provider import PromptBundle
from app.services.lesson_generator import LessonGeneratorService
from app.services.ncert_ingestion_service import NcertIngestionService
from app.services.ncert_retrieval_service import NcertRetrievalService


class ExplodingProvider:
    provider_name = "openai"

    def generate(self, prompt: PromptBundle) -> str:
        raise RuntimeError("simulated llm failure")


class EchoProvider:
    provider_name = "openai"

    def generate(self, prompt: PromptBundle) -> str:
        return f"Lesson Title\n{prompt.metadata['topic']}\n\nObjective\n{prompt.metadata['retrieved_snippets'][0]}\n\nOpening\nOpen\n\nMain Teaching\nTeach\n\nActivity\nDo\n\nQ&A\nAsk\n\nClosing\nClose"


def test_ncert_ingestion_from_json(db_session, tmp_path):
    source = tmp_path / "ncert.json"
    source.write_text(
        json.dumps(
            [
                {
                    "grade": "5",
                    "subject": "Science",
                    "chapter": "Plants",
                    "topic": "Plants",
                    "source_title": "Science 5 Plants",
                    "content": "Plants make food in leaves. Roots absorb water. Stems support the plant.",
                    "keywords": "plants, leaves, roots",
                }
            ]
        ),
        encoding="utf-8",
    )

    summary = NcertIngestionService(db_session).ingest_path(source)

    assert summary.files_processed == 1
    assert summary.records_processed == 1
    assert summary.chunks_created >= 1
    assert db_session.query(NcertContent).count() >= 1


def test_ncert_ingestion_from_csv(db_session, tmp_path):
    source = tmp_path / "ncert.csv"
    source.write_text(
        "grade,subject,chapter,topic,source_title,content,keywords\n"
        '5,Math,Fractions,Fractions,Math 5 Fractions,"A fraction is part of a whole. Use shapes and number lines.","fractions, whole"\n',
        encoding="utf-8",
    )

    summary = NcertIngestionService(db_session).ingest_path(source)

    assert summary.files_processed == 1
    assert summary.records_processed == 1
    assert summary.chunks_created >= 1
    row = db_session.query(NcertContent).one()
    assert row.subject == "Math"
    assert "fractions" in (row.keywords or "").lower()


def seed_retrieval_data(db_session):
    NcertIngestionService(db_session).ingest_path(Path("sample_data"))


def test_retrieval_filters_by_grade_and_subject(db_session):
    seed_retrieval_data(db_session)
    service = NcertRetrievalService(db_session)

    results = service.retrieve(grade="5", subject="Science", topic="plants")

    assert results
    assert all("NCERT EVS Grade 5" in item.source_title for item in results)
    assert all("fraction" not in item.content_chunk.lower() for item in results)


def test_retrieval_returns_top_relevant_chunks(db_session):
    seed_retrieval_data(db_session)
    service = NcertRetrievalService(db_session)

    results = service.retrieve(grade="5", subject="Math", topic="equivalent fractions")

    assert 1 <= len(results) <= 3
    assert results[0].score >= results[-1].score
    assert "fraction" in results[0].content_chunk.lower() or "fraction" in (results[0].topic or "").lower()


def test_lesson_generation_uses_retrieval_output(db_session):
    seed_retrieval_data(db_session)
    teacher = TeacherProfile(
        whatsapp_number="+15550002222",
        teacher_name="Anurag",
        default_grade="5",
        default_subject="Science",
        preferred_language="English",
    )
    db_session.add(teacher)
    db_session.commit()
    db_session.refresh(teacher)

    service = LessonGeneratorService(db_session, openai_provider=EchoProvider())
    service.settings.llm_provider = "openai"

    result = service.generate(teacher=teacher, topic="Plants", duration_minutes=35)

    assert "NCERT EVS Grade 5 - Plants Around Us" in result.lesson_text
    assert result.provider_used == "openai"


def test_deterministic_fallback_works_when_llm_disabled(db_session):
    seed_retrieval_data(db_session)
    teacher = TeacherProfile(
        whatsapp_number="+15550003333",
        teacher_name="Anurag",
        default_grade="5",
        default_subject="Science",
        preferred_language="English",
    )
    db_session.add(teacher)
    db_session.commit()
    db_session.refresh(teacher)

    service = LessonGeneratorService(db_session)
    result = service.generate(teacher=teacher, topic="Plants", duration_minutes=35)

    assert result.provider_used == "deterministic"
    assert "Lesson Title" in result.lesson_text


def test_graceful_fallback_when_llm_call_errors(db_session):
    seed_retrieval_data(db_session)
    teacher = TeacherProfile(
        whatsapp_number="+15550004444",
        teacher_name="Anurag",
        default_grade="5",
        default_subject="Science",
        preferred_language="English",
    )
    db_session.add(teacher)
    db_session.commit()
    db_session.refresh(teacher)

    service = LessonGeneratorService(db_session, openai_provider=ExplodingProvider())
    service.settings.llm_provider = "openai"
    result = service.generate(teacher=teacher, topic="Plants", duration_minutes=35)

    assert result.provider_used == "deterministic"
    assert "Lesson Title" in result.lesson_text
