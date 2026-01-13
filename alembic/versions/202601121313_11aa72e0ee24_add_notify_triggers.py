"""add_notify_triggers

Revision ID: 11aa72e0ee24
Revises: 3648749029ff
Create Date: 2026-01-12 13:13:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "11aa72e0ee24"
down_revision: str | Sequence[str] | None = "3648749029ff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add notification triggers."""
    # 1. Create the notify function
    op.execute("""
        CREATE OR REPLACE FUNCTION notify_event() RETURNS trigger AS $$
        DECLARE
            channel text;
        BEGIN
            -- Determine channel based on table name
            IF TG_TABLE_NAME = 'event_queue' THEN
                channel := 'new_event_queue_item';
            ELSIF TG_TABLE_NAME = 'command_outbox' THEN
                channel := 'new_command_outbox_item';
            ELSE
                channel := 'unknown_channel';
            END IF;

            PERFORM pg_notify(channel, '');
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # 2. Add triggers
    op.execute("""
        CREATE TRIGGER trigger_new_event
        AFTER INSERT ON event_queue
        FOR EACH ROW EXECUTE PROCEDURE notify_event();
    """)

    op.execute("""
        CREATE TRIGGER trigger_new_command
        AFTER INSERT ON command_outbox
        FOR EACH ROW EXECUTE PROCEDURE notify_event();
    """)


def downgrade() -> None:
    """Remove triggers and function."""
    op.execute("DROP TRIGGER IF EXISTS trigger_new_command ON command_outbox")
    op.execute("DROP TRIGGER IF EXISTS trigger_new_event ON event_queue")
    op.execute("DROP FUNCTION IF EXISTS notify_event")
