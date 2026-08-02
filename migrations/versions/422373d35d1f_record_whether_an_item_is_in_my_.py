"""Record whether an item is in My Publications

Revision ID: 422373d35d1f
Revises: c1b573deea88
Create Date: 2026-08-03 00:38:24.393628

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "422373d35d1f"
down_revision: str | Sequence[str] | None = "c1b573deea88"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("items", schema=None) as batch_op:
        # A server default the model does not declare: without one, adding a
        # NOT NULL column to a table that already holds items fails, and by now
        # there are databases with items in them. Nothing existing is in My
        # Publications, so false is the right answer for every one of them.
        batch_op.add_column(
            sa.Column(
                "in_publications",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.create_index(
            batch_op.f("ix_items_in_publications"), ["in_publications"], unique=False
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("items", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_items_in_publications"))
        batch_op.drop_column("in_publications")
