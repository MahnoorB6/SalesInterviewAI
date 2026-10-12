from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


class CandidateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=50)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be blank")
        return value


class CandidateResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    phone: str | None

    # Resume
    resume_uploaded: bool = False
    resume_analysis: dict | None = None

    # Latest role
    latest_role: str | None = None
    latest_company: str | None = None
    latest_role_start_date: str | None = None
    latest_role_end_date: str | None = None
    latest_role_description: str | None = None

    created_at: datetime | None = None

    class Config:
        from_attributes = True
