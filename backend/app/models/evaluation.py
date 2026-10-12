from sqlalchemy import (
    CheckConstraint,
    Column,
    Integer,
    Float,
    Text,
    String,
    ForeignKey,
    DateTime,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.database import Base


class Evaluation(Base):
    __tablename__ = "evaluations"
    __table_args__ = tuple(
        CheckConstraint(
            f"{field} IS NULL OR ({field} >= 0 AND {field} <= 100)",
            name=f"ck_evaluations_{field}_range",
        )
        for field in (
            "communication", "confidence", "sales_knowledge", "lead_qualification",
            "objection_handling", "persuasion", "closing_ability", "overall_score",
        )
    ) + (
        CheckConstraint(
            "result IS NULL OR result IN ('PASS', 'FAIL')",
            name="ck_evaluations_result",
        ),
        CheckConstraint(
            "recruiter_status IS NULL OR recruiter_status IN ('pending', 'approved', 'rejected')",
            name="ck_evaluations_recruiter_status",
        ),
    )

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    interview_id = Column(
        Integer,
        ForeignKey("interviews.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    communication = Column(
        Float,
        nullable=True,
    )

    confidence = Column(
        Float,
        nullable=True,
    )

    sales_knowledge = Column(
        Float,
        nullable=True,
    )

    lead_qualification = Column(
        Float,
        nullable=True,
    )

    objection_handling = Column(
        Float,
        nullable=True,
    )

    persuasion = Column(
        Float,
        nullable=True,
    )

    closing_ability = Column(
        Float,
        nullable=True,
    )

    overall_score = Column(
        Float,
        nullable=True,
    )

    result = Column(
        String(20),
        nullable=True,
    )

    recommendation = Column(
        Text,
        nullable=True,
    )

    strengths = Column(
        Text,
        nullable=True,
    )

    weaknesses = Column(
        Text,
        nullable=True,
    )

    question_scores = Column(
        Text,
        nullable=True,
    )

    structured_result = Column(JSONB, nullable=True)
    evaluation_status = Column(String(30), nullable=True)
    rubric_version = Column(String(50), nullable=True)
    evaluator_version = Column(String(50), nullable=True)
    evaluation_method = Column(String(50), nullable=True)

    # ========================================================
    # RECRUITER REVIEW
    # ========================================================

    recruiter_status = Column(
        String(20),
        nullable=True,
        default="pending",
        server_default=text("'pending'"),
    )

    reviewed_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=True)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True
    )

    # ========================================================
    # RELATIONSHIP
    # ========================================================

    interview = relationship("Interview", back_populates="evaluation")
    runs = relationship(
        "EvaluationRun",
        back_populates="evaluation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="EvaluationRun.id",
    )


class EvaluationRun(Base):
    """Append-only result snapshot; regeneration never erases prior provenance."""
    __tablename__ = "evaluation_runs"

    id = Column(Integer, primary_key=True)
    evaluation_id = Column(
        Integer,
        ForeignKey("evaluations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    structured_result = Column(JSONB, nullable=False)
    rubric_version = Column(String(50), nullable=False)
    evaluator_version = Column(String(50), nullable=False)
    evaluation_method = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    evaluation = relationship("Evaluation", back_populates="runs")
