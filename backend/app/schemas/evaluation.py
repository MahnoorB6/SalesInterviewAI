from datetime import datetime
import json

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class EvaluationCreate(BaseModel):
    interview_id: int = Field(gt=0)

    communication: float | None = Field(default=None, ge=0, le=100)
    confidence: float | None = Field(default=None, ge=0, le=100)
    sales_knowledge: float | None = Field(default=None, ge=0, le=100)
    lead_qualification: float | None = Field(default=None, ge=0, le=100)
    objection_handling: float | None = Field(default=None, ge=0, le=100)
    persuasion: float | None = Field(default=None, ge=0, le=100)
    closing_ability: float | None = Field(default=None, ge=0, le=100)

    overall_score: float | None = Field(default=None, ge=0, le=100)

    result: Literal["PASS", "FAIL"] | None = None

    recommendation: str | None = Field(default=None, max_length=4000)

    strengths: str | None = Field(default=None, max_length=12000)

    weaknesses: str | None = Field(default=None, max_length=12000)

    question_scores: str | None = Field(default=None, max_length=100000)

    @field_validator("question_scores")
    @classmethod
    def validate_question_scores(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError("question_scores must contain valid JSON") from error
        if not isinstance(parsed, list):
            raise ValueError("question_scores must be a JSON array")
        return value


class EvaluationResponse(BaseModel):
    id: int
    interview_id: int

    communication: float | None
    confidence: float | None
    sales_knowledge: float | None
    lead_qualification: float | None
    objection_handling: float | None
    persuasion: float | None
    closing_ability: float | None

    overall_score: float | None

    result: Literal["PASS", "FAIL"] | None

    recommendation: str | None

    strengths: str | None

    weaknesses: str | None

    question_scores: str | None

    recruiter_status: Literal["pending", "approved", "rejected"] | None

    reviewed_at: datetime | None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    structured_result: dict | None = None
    evaluation_status: str | None = None
    rubric_version: str | None = None
    evaluator_version: str | None = None
    evaluation_method: str | None = None
    runs: list["EvaluationRunResponse"] = Field(default_factory=list)

    class Config:
        from_attributes = True


class EvaluationRunResponse(BaseModel):
    id: int
    evaluation_id: int
    structured_result: dict
    rubric_version: str
    evaluator_version: str
    evaluation_method: str
    created_at: datetime | None = None

    class Config:
        from_attributes = True
