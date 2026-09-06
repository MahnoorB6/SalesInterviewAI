from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.database import Base


class Interview(Base):

    __tablename__ = "interviews"

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    candidate_id = Column(
        Integer,
        ForeignKey("candidates.id"),
        nullable=False,
    )

    position = Column(
        String(150),
        nullable=False,
        default="Sales Representative",
    )

    scheduled_at = Column(
        DateTime(timezone=True),
        nullable=False,
    )

    status = Column(
        String(50),
        nullable=False,
        default="scheduled",
    )

    meet_link = Column(
        String(500),
        nullable=True,
    )

    calendar_event_id = Column(
        String(500),
        nullable=True,
    )

    recording_path = Column(
        String(500),
        nullable=True,
    )

    transcript_path = Column(
        String(500),
        nullable=True,
    )

    notes = Column(
        Text,
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    candidate = relationship(
        "Candidate",
        backref="interviews",
    )