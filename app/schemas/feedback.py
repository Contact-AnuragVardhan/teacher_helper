from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class FeedbackChoiceOption(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=40)


class FeedbackQuestion(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    number: int = Field(ge=1)
    type: Literal["choice", "text"]
    text: str = Field(min_length=1, max_length=2000)
    required: bool = True


class FeedbackPart(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=255)
    questions: list[FeedbackQuestion] = Field(min_length=1)


class FeedbackSurveyDefinition(BaseModel):
    survey_id: str = Field(min_length=1, max_length=100)
    version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)
    choice_answer_format: str = Field(default="Yes / Sometimes / No", max_length=100)
    choice_options: list[FeedbackChoiceOption] = Field(min_length=1, max_length=3)
    parts: list[FeedbackPart] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "FeedbackSurveyDefinition":
        question_ids: set[str] = set()
        numbers: set[int] = set()
        for part in self.parts:
            for question in part.questions:
                if question.id in question_ids:
                    raise ValueError(f"Duplicate feedback question id: {question.id}")
                if question.number in numbers:
                    raise ValueError(f"Duplicate feedback question number: {question.number}")
                question_ids.add(question.id)
                numbers.add(question.number)
        return self

    @property
    def key(self) -> str:
        return f"{self.survey_id}:v{self.version}"

    def flattened_questions(self) -> list[tuple[FeedbackPart, FeedbackQuestion]]:
        return [
            (part, question)
            for part in self.parts
            for question in part.questions
        ]
