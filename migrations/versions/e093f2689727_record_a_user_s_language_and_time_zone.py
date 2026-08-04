"""Record a user's language and time zone

Both are nullable, and null is the setting rather than its absence: it means
"follow the browser", which is what every existing account gets.

Revision ID: e093f2689727
Revises: db4b448ae715
Create Date: 2026-08-04 14:08:09.755611

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e093f2689727"
down_revision: str | Sequence[str] | None = "db4b448ae715"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("language", sa.String(length=35), nullable=True))
        batch_op.add_column(sa.Column("time_zone", sa.String(length=64), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("time_zone")
        batch_op.drop_column("language")
