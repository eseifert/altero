"""Let a group member be restricted below the group's policy

Revision ID: cb22d67b3b38
Revises: fb5251b1453e
Create Date: 2026-08-12 00:04:00.158902

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cb22d67b3b38"
down_revision: str | Sequence[str] | None = "fb5251b1453e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    ``inherit`` is the value every existing membership takes, and it is the
    setting rather than a filler: it means the group's own policy decides, which
    is what every membership meant before this column existed. Nobody's access
    changes on upgrade.

    The same column goes on ``invitations``, because an offer of membership
    names the membership it offers: an invitation sent before this existed
    offers an unrestricted one, which is what it meant when it was sent.
    """
    for table in ("group_members", "invitations"):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "permission", sa.String(length=16), server_default="inherit", nullable=False
                )
            )


def downgrade() -> None:
    """Downgrade schema."""
    for table in ("invitations", "group_members"):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_column("permission")
