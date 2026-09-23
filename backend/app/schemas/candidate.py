from datetime import datetime

from pydantic import BaseModel, EmailStr


class CandidateCreate(BaseModel):
    name: str
    email: EmailStr
    phone: str | None = None


class CandidateResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    phone: str | None

    # Resume
    resume_path: str | None = None
    resume_text: str | None = None
    resume_analysis: dict | None = None

    # Latest role
    latest_role: str | None = None
    latest_company: str | None = None
    latest_role_start_date: str | None = None
    latest_role_end_date: str | None = None
    latest_role_description: str | None = None

    created_at: datetime

    class Config:
        from_attributes = True