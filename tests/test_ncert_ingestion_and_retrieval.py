from app.models.ncert_content import NcertContent
from app.models.teacher_profile import TeacherProfile
from app.services.lesson_generator import LessonGeneratorService
from app.services.ncert_retrieval_service import NcertRetrievalService


class EchoProvider:
    def generate_lesson(
        self,
        *,
        teacher,
        topic: str,
        duration_minutes: int,
        retrieved_chunks: list[dict],
    ) -> str:
        best = retrieved_chunks[0] if retrieved_chunks else {}

        return f"""
Lesson Title:
{topic}

Objective:
Book: {best.get('book', '')}
Unit: {best.get('chapter', '')}
Topic: {best.get('topic_name', '')}

Opening:
Start

Main Teaching:
Teach

Activity:
Do

Q&A:
Ask

Closing:
Close

Source:
{best.get('source_title', '')}
"""


def seed_retrieval_data(db_session):
    rows = [
        NcertContent(
            grade="5",
            subject="English",
            book="Looking Around",
            chapter="Plants Around Us",
            topic_name="Plants",
            source_title="NCERT EVS Grade 5 - Plants Around Us",
        ),
        NcertContent(
            grade="5",
            subject="English",
            book="Math Magic",
            chapter="Fractions",
            topic_name="Equivalent Fractions",
            source_title="NCERT Math Grade 5 - Fractions",
        ),
    ]

    db_session.add_all(rows)
    db_session.commit()


def test_ingestion_loads_structured_sample_data(db_session):
    seed_retrieval_data(db_session)

    retrieval = NcertRetrievalService(db_session)

    results = retrieval.retrieve(
        grade="5",
        subject="English",
        topic="Plants",
    )

    assert len(results) >= 1
    assert any(r["topic_name"] == "Plants" for r in results)


def test_retrieval_returns_top_relevant_chunks(db_session):
    seed_retrieval_data(db_session)

    service = NcertRetrievalService(db_session)

    results = service.retrieve(
        grade="5",
        subject="English",
        topic="fractions",
    )

    assert len(results) >= 1
    assert any("fraction" in r["topic_name"].lower() for r in results)


def test_lesson_generation_uses_retrieval_output(db_session):
    seed_retrieval_data(db_session)

    teacher = TeacherProfile(
        whatsapp_number="+15550002222",
        teacher_name="Anurag",
        default_grade="5",
        default_subject="English",
        preferred_language="English",
    )

    db_session.add(teacher)
    db_session.commit()

    service = LessonGeneratorService(db_session, openai_provider=EchoProvider())
    service.settings.llm_provider = "openai"

    result = service.generate(
        teacher=teacher,
        topic="Plants",
        duration_minutes=35,
    )

    assert "Plants Around Us" in result.lesson_text
    assert len(result.retrieved_chunks) >= 1