"""Refresh cached group metadata after adding membership arrays.

Revision ID: e97b23a41d06
Revises: a1d7c4e90b32
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e97b23a41d06"
down_revision: str | Sequence[str] | None = "a1d7c4e90b32"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Desktop fetches group metadata only when its advertised version changes.
    # Personal libraries have no group metadata and need no refresh.
    libraries = sa.table("libraries", sa.column("id"), sa.column("version"))
    groups = sa.table("groups", sa.column("library_id"))
    op.execute(
        libraries.update()
        .where(libraries.c.id.in_(sa.select(groups.c.library_id)))
        .values(version=libraries.c.version + 1)
    )


def downgrade() -> None:
    # Sync versions must never move backwards.
    pass
