"""Track provider message identities and resumable character deliveries."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6f12b7d83e40"
down_revision: str | Sequence[str] | None = "7d5f0d6a2b31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable metadata without changing existing immutable chat rows."""
    op.add_column(
        "chat_messages", sa.Column("external_message_id", sa.String(255), nullable=True)
    )
    op.add_column(
        "chat_messages", sa.Column("author_name", sa.String(255), nullable=True)
    )
    op.add_column(
        "chat_messages",
        sa.Column("reply_to_external_message_id", sa.String(255), nullable=True),
    )
    op.create_index(
        "uq_chat_messages_external_id",
        "chat_messages",
        ["platform", "external_message_id"],
        unique=True,
    )
    op.create_table(
        "speech_deliveries",
        sa.Column("source_message_id", sa.String(255), primary_key=True),
        sa.Column("guild_id", sa.String(255), nullable=False),
        sa.Column("channel_id", sa.String(255), nullable=False),
        sa.Column("finished", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_speech_deliveries_channel_id", "speech_deliveries", ["channel_id"]
    )


def downgrade() -> None:
    """Remove delivery tracking while preserving the original chat columns."""
    op.drop_table("speech_deliveries")
    op.drop_index("uq_chat_messages_external_id", table_name="chat_messages")
    for column in (
        "reply_to_external_message_id",
        "author_name",
        "external_message_id",
    ):
        op.drop_column("chat_messages", column)
