"""Store relations on collections

Revision ID: acd1e2a8ef04
Revises: 422373d35d1f
Create Date: 2026-08-03 08:55:31.976954

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "acd1e2a8ef04"
down_revision: str | Sequence[str] | None = "422373d35d1f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Mirrors item_relations: the object is part of the key, because one
    # predicate may name several collections.
    op.create_table(
        "collection_relations",
        sa.Column("collection_id", sa.Integer(), nullable=False),
        sa.Column("predicate", sa.String(length=64), nullable=False),
        sa.Column("object", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"]),
        sa.PrimaryKeyConstraint("collection_id", "predicate", "object"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("collection_relations")
