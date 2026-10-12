from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.statuses import InterviewStatus


class InterviewCreate(BaseModel):
    candidate_id: int = Field(gt=0)
    position: str = Field(default="Sales Representative", min_length=1, max_length=150)
    scheduled_at: datetime
    duration_minutes: int = Field(default=30, gt=0, le=480)
    meet_link: str | None = Field(default=None, max_length=500)

    @field_validator("position")
    @classmethod
    def clean_position(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Position cannot be blank")
        return value


class InterviewResponse(BaseModel):
    id: int
    candidate_id: int
    position: str
    scheduled_at: datetime
    status: InterviewStatus
    duration_minutes: int
    meet_link: str | None
    calendar_event_id: str | None
    recording_available: bool = False
    transcript_available: bool = False
    notes: str | None
    created_at: datetime | None
    completed_at: datetime | None

    class Config:
        from_attributes = True


class InterviewQuestionResponse(BaseModel):
    id: int
    interview_id: int
    question_number: int
    question: str
    category: str
    created_at: datetime | None

    class Config:
        from_attributes = True
