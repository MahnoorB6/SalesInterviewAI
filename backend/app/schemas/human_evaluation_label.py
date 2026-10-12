from typing import Literal

from pydantic import BaseModel, Field


class HumanEvaluationLabelCreate(BaseModel):
    interview_question_id: int = Field(gt=0)
    competency: str = Field(min_length=1, max_length=50)
    criterion: str = Field(min_length=1, max_length=100)
    rating: int = Field(ge=1, le=5)
    evidence_span: str = Field(min_length=1, max_length=4000)
    transcript_quality: Literal["good", "uncertain", "incomplete", "poor"]


class HumanEvaluationLabelResponse(BaseModel):
    id: int
    adjudication_status: str

    class Config:
        from_attributes = True
