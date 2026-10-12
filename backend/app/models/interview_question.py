from sqlalchemy import CheckConstraint, Column, Integer, Text, ForeignKey, UniqueConstraint, text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy import DateTime

from app.database.database import Base


class InterviewQuestion(Base):
    __tablename__ = "interview_questions"
    __table_args__ = (
        CheckConstraint("question_number > 0", name="ck_interview_questions_number_positive"),
        UniqueConstraint("interview_id", "question_number", name="uq_interview_questions_order"),
    )

    id = Column(Integer, primary_key=True, index=True)

    interview_id = Column(
        Integer,
        ForeignKey("interviews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    question_number = Column(Integer, nullable=False)

    question = Column(Text, nullable=False)

    category = Column(
        Text,
        nullable=False,
        default="role_specific",
        server_default=text("'role_specific'"),
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    interview = relationship("Interview", back_populates="questions")
