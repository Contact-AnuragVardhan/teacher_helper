from __future__ import annotations

import json
from pathlib import Path

from app.core.logging import get_logger, log_event
from app.schemas.feedback import FeedbackSurveyDefinition

logger = get_logger(__name__)


class FeedbackSurveyService:
    def __init__(self, survey_path: str | Path | None = None):
        self.survey_path = Path(survey_path) if survey_path else (
            Path(__file__).resolve().parents[1] / "data" / "weekly_lesson_plan_feedback.json"
        )

    def load(self) -> FeedbackSurveyDefinition:
        try:
            if not self.survey_path.is_file():
                raise FileNotFoundError(
                    "Feedback survey definition is missing at "
                    f"{self.survey_path}. Ensure app/data/weekly_lesson_plan_feedback.json "
                    "is committed and included in the deployed application."
                )
            payload = json.loads(self.survey_path.read_text(encoding="utf-8"))
            survey = FeedbackSurveyDefinition.model_validate(payload)
        except Exception as exc:
            log_event(
                logger,
                "feedback_survey_load_failed",
                path=str(self.survey_path),
                error=str(exc),
            )
            raise

        log_event(
            logger,
            "feedback_survey_loaded",
            survey_id=survey.survey_id,
            version=survey.version,
            question_count=len(survey.flattened_questions()),
        )
        return survey
