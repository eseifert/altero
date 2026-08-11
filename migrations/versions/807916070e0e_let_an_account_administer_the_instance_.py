"""Let an account administer the instance, or be taken out of service

Revision ID: 807916070e0e
Revises: 4316d74eba15
Create Date: 2026-08-11 18:48:47.950774

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "807916070e0e"
down_revision: str | Sequence[str] | None = "4316d74eba15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        # `sa.false()` rather than the `sa.text('0')` autogenerate wrote: that
        # is SQLite's spelling, and PostgreSQL refuses an integer default on a
        # boolean column outright.
        batch_op.add_column(
            sa.Column("administrator", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch_op.add_column(sa.Column("disabled_at", sa.DateTime(), nullable=True))

    # An instance that already exists has an account that claimed it, and the
    # rule for a new one is that the first account administers it. The lowest
    # id is that account: ids are assigned in sequence and never reused.
    # Without this an upgraded instance has an operator view nobody can open,
    # and the only way to a first administrator would be a shell on the server.
    #
    # Written as an expression rather than as SQL text so each backend spells
    # the boolean its own way: literal SQL saying `= 1` runs on SQLite and is
    # refused by PostgreSQL, which will not compare a boolean to an integer.
    users = sa.table("users", sa.column("id", sa.Integer), sa.column("administrator", sa.Boolean))
    op.execute(
        users.update()
        .where(users.c.id == sa.select(sa.func.min(users.c.id)).scalar_subquery())
        .values(administrator=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("disabled_at")
        batch_op.drop_column("administrator")
