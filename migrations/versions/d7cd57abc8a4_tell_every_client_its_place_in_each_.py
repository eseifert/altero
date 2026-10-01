"""Tell every client its place in each group

A group's JSON now carries ``admins`` and ``members``, without which the
desktop client makes a group library editable for its owner and nobody else.
A client that already holds a group fetches it again only when the version in
``/users/<id>/groups?format=versions`` differs from its own, so without this
every existing member stays read-only until something else is written to the
group. One step for every group library is the smallest change that makes each
client ask; a sync that finds nothing else new costs it nothing more.

Nothing to undo: a library version never moves backwards, and one taken is
harmless left in place.

Revision ID: d7cd57abc8a4
Revises: a1d7c4e90b32
Create Date: 2026-10-01 13:57:00.244162

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7cd57abc8a4"
down_revision: str | Sequence[str] | None = "a1d7c4e90b32"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    libraries = sa.table("libraries", sa.column("id", sa.Integer), sa.column("version", sa.Integer))
    groups = sa.table("groups", sa.column("library_id", sa.Integer))
    op.execute(
        libraries.update()
        .where(libraries.c.id.in_(sa.select(groups.c.library_id)))
        .values(version=libraries.c.version + 1)
    )


def downgrade() -> None:
    """Downgrade schema."""
