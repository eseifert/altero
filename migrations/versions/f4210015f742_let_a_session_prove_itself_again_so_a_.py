"""Let a session prove itself again, so a passwordless account can too

Revision ID: f4210015f742
Revises: af25402c0d41
Create Date: 2026-08-12 07:05:12.260986

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4210015f742"
down_revision: str | Sequence[str] | None = "af25402c0d41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nullable, and every existing session starts null: a browser signed in
    # before this existed has proved nothing under the new rule, which is the
    # safe direction. It will be asked for its password once, as it was for
    # every one of these operations before.
    with op.batch_alter_table("web_sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("reauthenticated", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("web_sessions", schema=None) as batch_op:
        batch_op.drop_column("reauthenticated")
