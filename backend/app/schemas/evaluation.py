from pydantic import BaseModel


class EvaluationCreate(BaseModel):
    interview_id: int

    communication: float | None = None
    confidence: float | None = None
    sales_knowledge: float | None = None
    lead_qualification: float | None = None
    objection_handling: float | None = None
    persuasion: float | None = None
    closing_ability: float | None = None

    overall_score: float | None = None
    recommendation: str | None = None
    strengths: str | None = None
    weaknesses: str | None = None


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
    recommendation: str | None
    strengths: str | None
    weaknesses: str | None

    class Config:
        from_attributes = True