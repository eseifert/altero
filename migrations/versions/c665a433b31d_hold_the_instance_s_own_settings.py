"""Hold the instance's own settings

Revision ID: c665a433b31d
Revises: 807916070e0e
Create Date: 2026-08-11 19:13:58.566003

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c665a433b31d"
down_revision: str | Sequence[str] | None = "807916070e0e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # No rows are written here. A setting exists only once somebody changes
    # it, and until then the value comes from the deployment's own
    # configuration -- so an instance upgraded into this keeps exactly the
    # behaviour it had, which for retention means deleting nothing.
    op.create_table(
        "instance_settings",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "updated",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("name"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("instance_settings")
