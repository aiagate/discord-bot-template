"""Add raw log scope schema fixes

Revision ID: 8c1f2a4b9d30
Revises: 7d13f0b5e3c1
Create Date: 2026-05-23 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8c1f2a4b9d30"
down_revision: str | Sequence[str] | None = "1e7cada58073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("chats", schema=None) as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("role", sa.String(length=32), nullable=True))
        batch_op.create_index(batch_op.f("ix_chats_user_id"), ["user_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_chats_role"), ["role"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("chats", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_chats_role"))
        batch_op.drop_index(batch_op.f("ix_chats_user_id"))
        batch_op.drop_column("role")
        batch_op.drop_column("user_id")
