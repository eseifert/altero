"""Index item flags behind their library

``deleted``, ``in_publications`` and ``item_type`` were indexed on their own,
spanning every library. Without statistics SQLite chose ``ix_items_deleted``
to count an item's children, reading every untrashed item in the instance; with
statistics it chooses the flag indexes over ``library_id`` for listings. One
composite index puts the flags behind the library they belong to.

``ix_items_library_id`` and ``ix_items_version`` go too: the first is a prefix
of three other indexes, and every filter on ``version`` comes with the library
and is served by ``ix_items_library_version``.

Revision ID: 5c3e8f1a9d27
Revises: d7cd57abc8a4
Create Date: 2026-10-16 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5c3e8f1a9d27"
down_revision: str | Sequence[str] | None = "d7cd57abc8a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The single-column indexes replaced, with the column each covered.
REPLACED = {
    "ix_items_deleted": "deleted",
    "ix_items_in_publications": "in_publications",
    "ix_items_item_type": "item_type",
    "ix_items_library_id": "library_id",
    "ix_items_version": "version",
}


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("items", schema=None) as batch_op:
        batch_op.create_index(
            "ix_items_library_deleted_parent",
            ["library_id", "deleted", "parent_id"],
            unique=False,
        )
        for name in REPLACED:
            batch_op.drop_index(name)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("items", schema=None) as batch_op:
        for name, column in REPLACED.items():
            batch_op.create_index(name, [column], unique=False)
        batch_op.drop_index("ix_items_library_deleted_parent")
