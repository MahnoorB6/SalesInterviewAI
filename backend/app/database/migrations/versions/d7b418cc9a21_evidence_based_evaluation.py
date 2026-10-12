"""add structured evaluation runs and future human-label storage

Revision ID: d7b418cc9a21
Revises: c2de709eb620
Create Date: 2026-10-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d7b418cc9a21"
down_revision: Union[str, Sequence[str], None] = "c2de709eb620"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evaluations", sa.Column("structured_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("evaluations", sa.Column("evaluation_status", sa.String(length=30), nullable=True))
    op.add_column("evaluations", sa.Column("rubric_version", sa.String(length=50), nullable=True))
    op.add_column("evaluations", sa.Column("evaluator_version", sa.String(length=50), nullable=True))
    op.add_column("evaluations", sa.Column("evaluation_method", sa.String(length=50), nullable=True))

    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("evaluation_id", sa.Integer(), nullable=False),
        sa.Column("structured_result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rubric_version", sa.String(length=50), nullable=False),
        sa.Column("evaluator_version", sa.String(length=50), nullable=False),
        sa.Column("evaluation_method", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["evaluation_id"], ["evaluations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_evaluation_runs_evaluation_id", "evaluation_runs", ["evaluation_id"])

    op.create_table(
        "human_evaluation_labels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("interview_id", sa.Integer(), nullable=True),
        sa.Column("interview_question_id", sa.Integer(), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("candidate_answer", sa.Text(), nullable=False),
        sa.Column("competency", sa.String(length=50), nullable=False),
        sa.Column("criterion", sa.String(length=100), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("evidence_span", sa.Text(), nullable=True),
        sa.Column("rater_id", sa.Integer(), nullable=False),
        sa.Column("rubric_version", sa.String(length=50), nullable=False),
        sa.Column("transcript_quality", sa.String(length=30), nullable=False),
        sa.Column("adjudication_status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_human_eval_label_rating"),
        sa.CheckConstraint("adjudication_status IN ('pending', 'adjudicated', 'rejected')", name="ck_human_eval_label_adjudication"),
        sa.ForeignKeyConstraint(["interview_id"], ["interviews.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["interview_question_id"], ["interview_questions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["rater_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("interview_question_id", "criterion", "rater_id", "rubric_version", name="uq_human_eval_label_rater_criterion_version"),
    )
    op.create_index("ix_human_evaluation_labels_interview_id", "human_evaluation_labels", ["interview_id"])
    op.create_index("ix_human_evaluation_labels_interview_question_id", "human_evaluation_labels", ["interview_question_id"])
    op.create_index("ix_human_evaluation_labels_rater_id", "human_evaluation_labels", ["rater_id"])


def downgrade() -> None:
    op.drop_index("ix_human_evaluation_labels_rater_id", table_name="human_evaluation_labels")
    op.drop_index("ix_human_evaluation_labels_interview_question_id", table_name="human_evaluation_labels")
    op.drop_index("ix_human_evaluation_labels_interview_id", table_name="human_evaluation_labels")
    op.drop_table("human_evaluation_labels")
    op.drop_index("ix_evaluation_runs_evaluation_id", table_name="evaluation_runs")
    op.drop_table("evaluation_runs")
    op.drop_column("evaluations", "evaluation_method")
    op.drop_column("evaluations", "evaluator_version")
    op.drop_column("evaluations", "rubric_version")
    op.drop_column("evaluations", "evaluation_status")
    op.drop_column("evaluations", "structured_result")
