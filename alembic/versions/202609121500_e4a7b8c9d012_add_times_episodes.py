"""Track Times episode delivery plans and continuity progress."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e4a7b8c9d012"
down_revision: str | Sequence[str] | None = "6f12b7d83e40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the times_episodes table."""
    op.create_table(
        "times_episodes",
        sa.Column("source_message_id", sa.String(255), primary_key=True),
        sa.Column("guild_id", sa.String(255), nullable=False),
        sa.Column("channel_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("next_post_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_times_episodes_channel_id", "times_episodes", ["channel_id"])
    op.create_index("ix_times_episodes_status", "times_episodes", ["status"])


def downgrade() -> None:
    """Remove times_episodes table."""
    op.drop_index("ix_times_episodes_status", table_name="times_episodes")
    op.drop_index("ix_times_episodes_channel_id", table_name="times_episodes")
    op.drop_table("times_episodes")
