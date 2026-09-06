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
    created_at: datetime

    class Config:
        from_attributes = True