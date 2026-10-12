from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.database.database import Base


class HumanEvaluationLabel(Base):
    """Empty-by-default annotation storage for future real, adjudicated labels."""
    __tablename__ = "human_evaluation_labels"
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_human_eval_label_rating"),
        CheckConstraint(
            "adjudication_status IN ('pending', 'adjudicated', 'rejected')",
            name="ck_human_eval_label_adjudication",
        ),
        UniqueConstraint(
            "interview_question_id", "criterion", "rater_id", "rubric_version",
            name="uq_human_eval_label_rater_criterion_version",
        ),
    )

    id = Column(Integer, primary_key=True)
    interview_id = Column(Integer, ForeignKey("interviews.id", ondelete="SET NULL"), nullable=True, index=True)
    interview_question_id = Column(
        Integer,
        ForeignKey("interview_questions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    question = Column(Text, nullable=False)
    candidate_answer = Column(Text, nullable=False)
    competency = Column(String(50), nullable=False)
    criterion = Column(String(100), nullable=False)
    rating = Column(Integer, nullable=False)
    evidence_span = Column(Text, nullable=True)
    rater_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    rubric_version = Column(String(50), nullable=False)
    transcript_quality = Column(String(30), nullable=False)
    adjudication_status = Column(String(20), nullable=False, default="pending", server_default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
