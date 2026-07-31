"""Index the link tables by their second column

Revision ID: c1b573deea88
Revises: 76839e611393
Create Date: 2026-08-01 00:43:30.615612

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1b573deea88"
down_revision: str | Sequence[str] | None = "76839e611393"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Each link table's primary key covers lookups by its first column only.
    # Tag listings read `item_tags` by tag, and rendering an item reads
    # `collection_items` by item, so both directions need an index.
    op.create_index("ix_item_tags_tag_id", "item_tags", ["tag_id"])
    op.create_index("ix_collection_items_item_id", "collection_items", ["item_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_collection_items_item_id", table_name="collection_items")
    op.drop_index("ix_item_tags_tag_id", table_name="item_tags")
