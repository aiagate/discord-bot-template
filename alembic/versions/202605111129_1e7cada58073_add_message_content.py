"""Add Message Content

Revision ID: 1e7cada58073
Revises: 49f4e4f835ac
Create Date: 2026-05-11 11:29:55.024614

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "1e7cada58073"
down_revision: str | Sequence[str] | None = "49f4e4f835ac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # `message_content` already exists in the initial chats table migration.
    # Keep this revision as a no-op so fresh databases can upgrade cleanly.
    return None


def downgrade() -> None:
    """Downgrade schema."""
    # Nothing to roll back because this revision does not change schema.
    return None
