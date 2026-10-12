"""align application models and database schema

Revision ID: 9ac042be712f
Revises: 6f0553223ec4
Create Date: 2026-10-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "9ac042be712f"
down_revision: Union[str, Sequence[str], None] = "6f0553223ec4"
branch_labels = None
depends_on = None


STATUSES = ("scheduled", "in_progress", "completed", "cancelled", "interrupted", "failed")
SCORE_FIELDS = (
    "communication",
    "confidence",
    "sales_knowledge",
    "lead_qualification",
    "objection_handling",
    "persuasion",
    "closing_ability",
    "overall_score",
)


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table_name: str) -> bool:
    return table_name in _inspector().get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    return column_name in {
        column["name"] for column in _inspector().get_columns(table_name)
    }


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if not _has_column(table_name, column.name):
        op.add_column(table_name, column)


def _has_check(table_name: str, name: str) -> bool:
    return any(item.get("name") == name for item in _inspector().get_check_constraints(table_name))


def _ensure_cascade_foreign_key(table_name: str, local_column: str, target_table: str, name: str) -> None:
    foreign_keys = _inspector().get_foreign_keys(table_name)
    matching = [fk for fk in foreign_keys if fk.get("constrained_columns") == [local_column]]
    if any(
        fk.get("name") == name
        and (fk.get("options") or {}).get("ondelete", "").upper() == "CASCADE"
        for fk in matching
    ):
        return
    for fk in matching:
        if fk.get("name"):
            op.drop_constraint(fk["name"], table_name, type_="foreignkey")
    op.create_foreign_key(
        name,
        table_name,
        target_table,
        [local_column],
        ["id"],
        ondelete="CASCADE",
    )


def _validate_existing_data() -> None:
    connection = op.get_bind()

    if _has_table("interviews"):
        statuses = set(connection.execute(sa.text("SELECT DISTINCT status FROM interviews")).scalars())
        invalid = statuses - set(STATUSES)
        if invalid:
            raise RuntimeError(
                "Cannot add interview status constraint; unsupported existing statuses found: "
                + ", ".join(sorted(str(value) for value in invalid))
                + ". Correct these rows explicitly, then rerun the migration."
            )

    if _has_table("evaluations"):
        for field in SCORE_FIELDS:
            if _has_column("evaluations", field):
                count = connection.execute(
                    sa.text(f"SELECT count(*) FROM evaluations WHERE {field} < 0 OR {field} > 100")
                ).scalar_one()
                if count:
                    raise RuntimeError(
                        f"Cannot constrain evaluations.{field}; {count} existing values are outside 0..100."
                    )
        if _has_column("evaluations", "recruiter_status"):
            invalid_reviews = connection.execute(
                sa.text(
                    "SELECT DISTINCT recruiter_status FROM evaluations "
                    "WHERE recruiter_status IS NOT NULL "
                    "AND recruiter_status NOT IN ('pending', 'approved', 'rejected')"
                )
            ).scalars().all()
            if invalid_reviews:
                raise RuntimeError(
                    "Cannot add recruiter status constraint; unsupported existing values found: "
                    + ", ".join(sorted(str(value) for value in invalid_reviews))
                )
        if _has_column("evaluations", "result"):
            invalid_results = connection.execute(
                sa.text(
                    "SELECT DISTINCT result FROM evaluations "
                    "WHERE result IS NOT NULL AND result NOT IN ('PASS', 'FAIL')"
                )
            ).scalars().all()
            if invalid_results:
                raise RuntimeError(
                    "Cannot add evaluation result constraint; unsupported existing values found: "
                    + ", ".join(sorted(str(value) for value in invalid_results))
                )

    if _has_table("interview_questions"):
        duplicates = connection.execute(
            sa.text(
                "SELECT interview_id, question_number FROM interview_questions "
                "GROUP BY interview_id, question_number HAVING count(*) > 1 LIMIT 1"
            )
        ).first()
        if duplicates:
            raise RuntimeError(
                "Cannot add interview question ordering constraint; duplicate ordering exists "
                f"for interview {duplicates[0]} question number {duplicates[1]}."
            )


def upgrade() -> None:
    # These additions repair the schema produced by the existing migration chain.
    for column in (
        sa.Column("resume_path", sa.String(length=500), nullable=True),
        sa.Column("resume_text", sa.Text(), nullable=True),
        sa.Column("resume_analysis", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("latest_role", sa.String(length=255), nullable=True),
        sa.Column("latest_company", sa.String(length=255), nullable=True),
        sa.Column("latest_role_start_date", sa.String(length=50), nullable=True),
        sa.Column("latest_role_end_date", sa.String(length=50), nullable=True),
        sa.Column("latest_role_description", sa.Text(), nullable=True),
    ):
        _add_column_if_missing("candidates", column)

    _add_column_if_missing("interviews", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing(
        "interviews",
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default=sa.text("30")),
    )

    if not _has_table("interview_questions"):
        op.create_table(
            "interview_questions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("interview_id", sa.Integer(), nullable=False),
            sa.Column("question_number", sa.Integer(), nullable=False),
            sa.Column("question", sa.Text(), nullable=False),
            sa.Column("category", sa.Text(), nullable=False, server_default=sa.text("'role_specific'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["interview_id"], ["interviews.id"], name="fk_interview_questions_interview_id_interviews", ondelete="CASCADE"),
            sa.CheckConstraint("question_number > 0", name="ck_interview_questions_number_positive"),
            sa.UniqueConstraint("interview_id", "question_number", name="uq_interview_questions_order"),
        )
    else:
        _add_column_if_missing("interview_questions", sa.Column("category", sa.Text(), nullable=False, server_default=sa.text("'role_specific'")))
        _add_column_if_missing(
            "interview_questions",
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    for column in (
        sa.Column("result", sa.String(length=20), nullable=True),
        sa.Column("question_scores", sa.Text(), nullable=True),
        sa.Column("recruiter_status", sa.String(length=20), nullable=True, server_default=sa.text("'pending'")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
    ):
        _add_column_if_missing("evaluations", column)

    if _has_column("evaluations", "recommendation"):
        op.alter_column(
            "evaluations",
            "recommendation",
            existing_type=sa.String(length=100),
            type_=sa.Text(),
            existing_nullable=True,
            postgresql_using="recommendation::text",
        )

    _validate_existing_data()

    _ensure_cascade_foreign_key("interviews", "candidate_id", "candidates", "fk_interviews_candidate_id_candidates")
    _ensure_cascade_foreign_key("evaluations", "interview_id", "interviews", "fk_evaluations_interview_id_interviews")
    _ensure_cascade_foreign_key("interview_questions", "interview_id", "interviews", "fk_interview_questions_interview_id_interviews")

    op.alter_column(
        "interviews",
        "status",
        existing_type=sa.String(length=50),
        existing_nullable=False,
        server_default=sa.text("'scheduled'"),
    )

    if not _has_check("interviews", "ck_interviews_status"):
        values = ", ".join("'" + value + "'" for value in STATUSES)
        op.create_check_constraint("ck_interviews_status", "interviews", f"status IN ({values})")
    if not _has_check("interviews", "ck_interviews_duration_positive"):
        op.create_check_constraint("ck_interviews_duration_positive", "interviews", "duration_minutes > 0")
    if not _has_check("evaluations", "ck_evaluations_recruiter_status"):
        op.create_check_constraint(
            "ck_evaluations_recruiter_status",
            "evaluations",
            "recruiter_status IS NULL OR recruiter_status IN ('pending', 'approved', 'rejected')",
        )
    if not _has_check("evaluations", "ck_evaluations_result"):
        op.create_check_constraint(
            "ck_evaluations_result", "evaluations", "result IS NULL OR result IN ('PASS', 'FAIL')"
        )
    for field in SCORE_FIELDS:
        name = f"ck_evaluations_{field}_range"
        if not _has_check("evaluations", name):
            op.create_check_constraint(name, "evaluations", f"{field} IS NULL OR ({field} >= 0 AND {field} <= 100)")
    if not _has_check("interview_questions", "ck_interview_questions_number_positive"):
        op.create_check_constraint("ck_interview_questions_number_positive", "interview_questions", "question_number > 0")
    if not any(
        item.get("name") == "uq_interview_questions_order"
        for item in _inspector().get_unique_constraints("interview_questions")
    ):
        op.create_unique_constraint(
            "uq_interview_questions_order", "interview_questions", ["interview_id", "question_number"]
        )
    if not any(
        "interview_id" in (item.get("column_names") or [])
        for item in _inspector().get_unique_constraints("evaluations")
    ):
        op.create_unique_constraint("uq_evaluations_interview_id", "evaluations", ["interview_id"])
    if "ix_interview_questions_interview_id" not in {item["name"] for item in _inspector().get_indexes("interview_questions")}:
        op.create_index("ix_interview_questions_interview_id", "interview_questions", ["interview_id"])
    if "ix_interview_questions_id" not in {item["name"] for item in _inspector().get_indexes("interview_questions")}:
        op.create_index("ix_interview_questions_id", "interview_questions", ["id"])
    if "ix_interviews_status" not in {item["name"] for item in _inspector().get_indexes("interviews")}:
        op.create_index("ix_interviews_status", "interviews", ["status"])


def downgrade() -> None:
    # Drop only constraints and columns introduced by this revision.
    for field in SCORE_FIELDS:
        op.drop_constraint(f"ck_evaluations_{field}_range", "evaluations", type_="check")
    op.drop_constraint("ck_evaluations_recruiter_status", "evaluations", type_="check")
    op.drop_constraint("ck_evaluations_result", "evaluations", type_="check")
    op.drop_constraint("ck_interviews_status", "interviews", type_="check")
    op.drop_constraint("ck_interviews_duration_positive", "interviews", type_="check")
    op.drop_constraint("uq_interview_questions_order", "interview_questions", type_="unique")
    op.drop_constraint("ck_interview_questions_number_positive", "interview_questions", type_="check")
    op.drop_index("ix_interview_questions_interview_id", table_name="interview_questions")
    op.drop_index("ix_interview_questions_id", table_name="interview_questions")
    op.drop_index("ix_interviews_status", table_name="interviews")
    op.drop_constraint("fk_interview_questions_interview_id_interviews", "interview_questions", type_="foreignkey")
    op.drop_constraint("fk_evaluations_interview_id_interviews", "evaluations", type_="foreignkey")
    op.drop_constraint("fk_interviews_candidate_id_candidates", "interviews", type_="foreignkey")
    op.create_foreign_key(None, "interviews", "candidates", ["candidate_id"], ["id"])
    op.create_foreign_key(None, "evaluations", "interviews", ["interview_id"], ["id"])
    op.alter_column(
        "interviews", "status", existing_type=sa.String(length=50), server_default=None
    )
    op.drop_table("interview_questions")
    op.drop_column("evaluations", "updated_at")
    op.drop_column("evaluations", "created_at")
    op.drop_column("evaluations", "reviewed_at")
    op.drop_column("evaluations", "recruiter_status")
    op.drop_column("evaluations", "question_scores")
    op.drop_column("evaluations", "result")
    op.drop_column("interviews", "duration_minutes")
    op.drop_column("interviews", "completed_at")
    for name in (
        "latest_role_description", "latest_role_end_date", "latest_role_start_date",
        "latest_company", "latest_role", "resume_analysis", "resume_text", "resume_path",
    ):
        op.drop_column("candidates", name)
