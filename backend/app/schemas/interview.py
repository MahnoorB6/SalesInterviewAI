from datetime import datetime

from pydantic import BaseModel


class InterviewCreate(BaseModel):
    candidate_id: int
    position: str
    scheduled_at: datetime
    meet_link: str | None = None


class InterviewResponse(BaseModel):
    id: int
    candidate_id: int
    position: str
    scheduled_at: datetime
    status: str
    meet_link: str | None
    calendar_event_id: str | None
    recording_path: str | None
    transcript_path: str | None
    notes: str | None
    created_at: datetime

    class Config:
        from_attributes = True