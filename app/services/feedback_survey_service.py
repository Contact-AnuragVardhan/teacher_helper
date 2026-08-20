from __future__ import annotations

import json
from pathlib import Path

from app.core.language import language_key
from app.core.logging import get_logger, log_event
from app.schemas.feedback import FeedbackSurveyDefinition

logger = get_logger(__name__)


class FeedbackSurveyService:
    """Load the weekly feedback survey in the teacher's preferred language."""

    _LANGUAGE_FILENAMES = {
        "english": "weekly_lesson_plan_feedback.json",
        "hinglish": "weekly_lesson_plan_feedback.hinglish.json",
        "hindi": "weekly_lesson_plan_feedback.hindi.json",
    }

    def __init__(self, survey_path: str | Path | None = None):
        self._custom_survey_path = Path(survey_path) if survey_path else None
        self.data_dir = Path(__file__).resolve().parents[1] / "data"
        # Preserve the existing public attribute for compatibility/tests.
        self.survey_path = self._custom_survey_path or (
            self.data_dir / self._LANGUAGE_FILENAMES["english"]
        )

    def survey_path_for_language(self, language: str | None = None) -> Path:
        # An explicitly supplied path remains authoritative for callers/tests that
        # intentionally inject a custom survey definition.
        if self._custom_survey_path is not None:
            return self._custom_survey_path

        key = language_key(language)
        filename = self._LANGUAGE_FILENAMES.get(
            key,
            self._LANGUAGE_FILENAMES["english"],
        )
        return self.data_dir / filename

    def load(self, language: str | None = None) -> FeedbackSurveyDefinition:
        survey_path = self.survey_path_for_language(language)
        try:
            if not survey_path.is_file():
                raise FileNotFoundError(
                    "Feedback survey definition is missing at "
                    f"{survey_path}. Ensure all app/data/weekly_lesson_plan_feedback*.json "
                    "files are committed and included in the deployed application."
                )
            payload = json.loads(survey_path.read_text(encoding="utf-8"))
            survey = FeedbackSurveyDefinition.model_validate(payload)
        except Exception as exc:
            log_event(
                logger,
                "feedback_survey_load_failed",
                path=str(survey_path),
                language=language_key(language),
                error=str(exc),
            )
            raise

        log_event(
            logger,
            "feedback_survey_loaded",
            survey_id=survey.survey_id,
            version=survey.version,
            language=language_key(language),
            path=str(survey_path),
            question_count=len(survey.flattened_questions()),
        )
        return survey
