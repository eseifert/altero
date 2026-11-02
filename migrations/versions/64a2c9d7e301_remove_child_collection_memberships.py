"""Remove child collection memberships and make clients download the repair.

Revision ID: 64a2c9d7e301
Revises: ae39b4d8c021
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "64a2c9d7e301"
down_revision = "ae39b4d8c021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    libraries = sa.table("libraries", sa.column("id"), sa.column("version"))
    items = sa.table(
        "items",
        sa.column("id"),
        sa.column("library_id"),
        sa.column("parent_id"),
        sa.column("version"),
        sa.column("server_date_modified", sa.DateTime()),
    )
    links = sa.table("collection_items", sa.column("item_id"))
    affected = sa.select(items.c.id).where(
        items.c.parent_id.is_not(None),
        items.c.id.in_(sa.select(links.c.item_id)),
    )
    connection = op.get_bind()
    library_ids = connection.scalars(
        sa.select(items.c.library_id).where(items.c.id.in_(affected)).distinct()
    ).all()
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    for library_id in library_ids:
        # One new version per affected library. Updating only the links would
        # leave already-synced desktops holding the invalid cached response.
        connection.execute(
            libraries.update()
            .where(libraries.c.id == library_id)
            .values(version=libraries.c.version + 1)
        )
        version = connection.scalar(
            sa.select(libraries.c.version).where(libraries.c.id == library_id)
        )
        connection.execute(
            items.update()
            .where(items.c.library_id == library_id, items.c.id.in_(affected))
            .values(version=version, server_date_modified=now)
        )
    connection.execute(links.delete().where(links.c.item_id.in_(affected)))


def downgrade() -> None:
    """Keep repaired data: invalid memberships cannot be restored safely."""
