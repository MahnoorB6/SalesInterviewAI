from sqlalchemy import Column, Integer, Text, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy import DateTime

from app.database.database import Base


class InterviewQuestion(Base):
    __tablename__ = "interview_questions"

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
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )