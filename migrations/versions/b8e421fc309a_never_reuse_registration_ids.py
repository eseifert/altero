"""Keep request IDs monotonic after retention cleanup on SQLite.

Revision ID: b8e421fc309a
Revises: a7d931bc205e
"""

from alembic import op

revision = "b8e421fc309a"
down_revision = "a7d931bc205e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(
            "registration_requests", recreate="always", table_kwargs={"sqlite_autoincrement": True}
        ):
            pass


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(
            "registration_requests", recreate="always", table_kwargs={"sqlite_autoincrement": False}
        ):
            pass
