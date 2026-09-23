from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.database.database import Base


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(Integer, primary_key=True, index=True)

    # Basic candidate information
    name = Column(String(150), nullable=False)
    email = Column(String(255), nullable=False, unique=True, index=True)
    phone = Column(String(50), nullable=True)

    # Resume
    resume_path = Column(String(500), nullable=True)
    resume_text = Column(Text, nullable=True)
    resume_analysis = Column(JSONB, nullable=True)

    # Latest/current role
    latest_role = Column(String(255), nullable=True)
    latest_company = Column(String(255), nullable=True)
    latest_role_start_date = Column(String(50), nullable=True)
    latest_role_end_date = Column(String(50), nullable=True)
    latest_role_description = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )