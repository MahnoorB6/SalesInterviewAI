"""add position and calendar event id to interviews"""

from alembic import op
import sqlalchemy as sa


# ============================================================
# REVISION IDENTIFIERS
# ============================================================

revision = "6f0553223ec4"

down_revision = "36f75fc7e673"

branch_labels = None

depends_on = None


# ============================================================
# UPGRADE
# ============================================================

def upgrade():

    # --------------------------------------------------------
    # Add position temporarily as nullable
    # --------------------------------------------------------

    op.add_column(
        "interviews",
        sa.Column(
            "position",
            sa.String(length=150),
            nullable=True,
        ),
    )

    # --------------------------------------------------------
    # Fill existing interview records
    # --------------------------------------------------------

    op.execute(
        """
        UPDATE interviews
        SET position = 'Sales Representative'
        WHERE position IS NULL
        """
    )

    # --------------------------------------------------------
    # Make position required
    # --------------------------------------------------------

    op.alter_column(
        "interviews",
        "position",
        existing_type=sa.String(length=150),
        nullable=False,
    )

    # --------------------------------------------------------
    # Add Google Calendar event ID
    # --------------------------------------------------------

    op.add_column(
        "interviews",
        sa.Column(
            "calendar_event_id",
            sa.String(length=500),
            nullable=True,
        ),
    )


# ============================================================
# DOWNGRADE
# ============================================================

def downgrade():

    op.drop_column(
        "interviews",
        "calendar_event_id",
    )

    op.drop_column(
        "interviews",
        "position",
    )