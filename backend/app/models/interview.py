from sqlalchemy import CheckConstraint, Column, Integer, String, DateTime, ForeignKey, Text, text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.database import Base
from app.statuses import INTERVIEW_STATUS_VALUES, InterviewStatus


class Interview(Base):

    __tablename__ = "interviews"
    __table_args__ = (
        CheckConstraint(
            "status IN (" + ", ".join(repr(value) for value in INTERVIEW_STATUS_VALUES) + ")",
            name="ck_interviews_status",
        ),
        CheckConstraint("duration_minutes > 0", name="ck_interviews_duration_positive"),
    )

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    candidate_id = Column(
        Integer,
        ForeignKey("candidates.id", ondelete="CASCADE"),
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

    duration_minutes = Column(Integer, nullable=False, default=30, server_default=text("30"))

    # Values are defined in app.statuses.InterviewStatus.
    status = Column(
        String(50),
        nullable=False,
        default=InterviewStatus.SCHEDULED.value,
        server_default=text("'scheduled'"),
        index=True,
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

    completed_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    candidate = relationship(
        "Candidate",
        back_populates="interviews",
    )

    questions = relationship(
        "InterviewQuestion",
        back_populates="interview",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="InterviewQuestion.question_number",
    )
    evaluation = relationship(
        "Evaluation",
        back_populates="interview",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )

    @property
    def transcript_available(self) -> bool:
        return bool(self.transcript_path)

    @property
    def recording_available(self) -> bool:
        return bool(self.recording_path)
