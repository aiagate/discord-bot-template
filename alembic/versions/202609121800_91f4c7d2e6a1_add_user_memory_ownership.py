"""Add canonical user ownership and long-term memory source markers."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "91f4c7d2e6a1"
down_revision: str | Sequence[str] | None = "e4a7b8c9d012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable ownership, explicit provider mappings, and source markers."""
    with op.batch_alter_table(
        "chat_messages", schema=None, recreate="always"
    ) as batch_op:
        batch_op.add_column(
            sa.Column(
                "user_id",
                sa.String(length=26),
                sa.ForeignKey("users.id", name="fk_chat_messages_user_id_users"),
                nullable=True,
            )
        )
    op.create_index("ix_chat_messages_user_id", "chat_messages", ["user_id"])
    op.create_table(
        "user_channel_identities",
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("external_participant_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(length=26), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("platform", "external_participant_id"),
    )
    op.create_index(
        "ix_user_channel_identities_user_id",
        "user_channel_identities",
        ["user_id"],
    )
    op.create_table(
        "memory_consolidated_chat_sources",
        sa.Column("chat_message_id", sa.String(length=26), nullable=False),
        sa.Column("consolidated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chat_message_id"], ["chat_messages.id"]),
        sa.PrimaryKeyConstraint("chat_message_id"),
    )


def downgrade() -> None:
    """Remove ownership and consolidation metadata."""
    op.drop_table("memory_consolidated_chat_sources")
    op.drop_index(
        "ix_user_channel_identities_user_id", table_name="user_channel_identities"
    )
    op.drop_table("user_channel_identities")
    op.drop_index("ix_chat_messages_user_id", table_name="chat_messages")
    with op.batch_alter_table(
        "chat_messages", schema=None, recreate="always"
    ) as batch_op:
        batch_op.drop_column("user_id")
