"""Let an account decide who sees its profile

Every existing account gets ``public``, which is the behaviour it already had:
``/users/<id>/publications/items`` has always answered without a key, so a
column defaulting to anything else would quietly unpublish work that its owner
published on purpose.

Revision ID: 40b83b1acb4c
Revises: 60dbda3ba678
Create Date: 2026-08-09 14:40:57.352801

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "40b83b1acb4c"
down_revision: str | Sequence[str] | None = "60dbda3ba678"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "profile_visibility",
                sa.Enum(
                    "PUBLIC",
                    "USERS",
                    "PRIVATE",
                    name="profilevisibility",
                    native_enum=False,
                    length=8,
                ),
                server_default="public",
                nullable=False,
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("profile_visibility")
