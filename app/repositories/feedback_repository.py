from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.logging import get_logger, log_event
from app.models.feedback_submission import FeedbackSubmission
from app.schemas.feedback import FeedbackSurveyDefinition

logger = get_logger(__name__)


class FeedbackRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_submission(
        self,
        *,
        teacher,
        whatsapp_number: str,
        survey: FeedbackSurveyDefinition,
        answers: dict[str, str],
    ) -> FeedbackSubmission:
        question_lookup = {
            question.id: question
            for _, question in survey.flattened_questions()
        }

        answer_rows = []
        for _, question in survey.flattened_questions():
            if question.id not in answers:
                continue
            answer_rows.append(
                {
                    "question_id": question.id,
                    "question_number": question.number,
                    "question_type": question.type,
                    "question": question.text,
                    "answer": answers[question.id],
                }
            )

        payload = {
            "survey_id": survey.survey_id,
            "survey_version": survey.version,
            "survey_title": survey.title,
            "submitted_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "answers": answer_rows,
        }

        submission = FeedbackSubmission(
            teacher_id=teacher.id,
            whatsapp_number=whatsapp_number,
            survey_id=survey.survey_id,
            survey_version=survey.version,
            teacher_name=teacher.teacher_name,
            school_name=getattr(teacher, "school_name", None),
            grade=teacher.default_grade,
            subject=teacher.default_subject,
            preferred_language=teacher.preferred_language,
            answers_json=json.dumps(payload, ensure_ascii=False),
        )
        self.db.add(submission)
        self.db.commit()
        self.db.refresh(submission)

        log_event(
            logger,
            "feedback_submission_created",
            feedback_submission_id=submission.id,
            teacher_id=teacher.id,
            survey_id=survey.survey_id,
            survey_version=survey.version,
            answered_count=len(answer_rows),
        )
        return submission

    def list_answer_texts(
        self,
        *,
        teacher_id: int,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[str]:
        submissions = (
            self.db.query(FeedbackSubmission)
            .filter(
                FeedbackSubmission.teacher_id == teacher_id,
                FeedbackSubmission.submitted_at >= start_utc,
                FeedbackSubmission.submitted_at < end_utc,
            )
            .order_by(FeedbackSubmission.submitted_at.asc(), FeedbackSubmission.id.asc())
            .all()
        )

        answers: list[str] = []
        for submission in submissions:
            try:
                payload = json.loads(submission.answers_json or "{}")
            except json.JSONDecodeError:
                continue
            for item in payload.get("answers", []):
                answer = str((item or {}).get("answer") or "").strip()
                if answer:
                    answers.append(answer)
        return answers

