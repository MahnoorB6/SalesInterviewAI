"""require interview question creation timestamps

Revision ID: c2de709eb620
Revises: 9ac042be712f
Create Date: 2026-10-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c2de709eb620"
down_revision: Union[str, Sequence[str], None] = "9ac042be712f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    column = next(
        item
        for item in inspector.get_columns("interview_questions")
        if item["name"] == "created_at"
    )
    if column["nullable"]:
        null_count = op.get_bind().execute(
            sa.text("SELECT count(*) FROM interview_questions WHERE created_at IS NULL")
        ).scalar_one()
        if null_count:
            raise RuntimeError(
                "Cannot require interview question created_at; "
                f"{null_count} existing rows have no timestamp. No rows were changed."
            )
        op.alter_column(
            "interview_questions",
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=True,
            nullable=False,
        )


def downgrade() -> None:
    op.alter_column(
        "interview_questions",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        nullable=True,
    )
