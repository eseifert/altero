"""Hold the links that share one collection

Revision ID: af25402c0d41
Revises: cb22d67b3b38
Create Date: 2026-08-12 00:04:44.897711

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "af25402c0d41"
down_revision: str | Sequence[str] | None = "cb22d67b3b38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "collection_shares",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("library_id", sa.Integer(), nullable=False),
        sa.Column("collection_id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created", sa.DateTime(), nullable=False),
        sa.Column("expires", sa.DateTime(), nullable=True),
        sa.Column("subcollections", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("files", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("last_used", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["library_id"],
            ["libraries.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("collection_shares", schema=None) as batch_op:
        batch_op.create_index("ix_collection_shares_collection", ["collection_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_collection_shares_library_id"), ["library_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_collection_shares_token"), ["token"], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("collection_shares", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_collection_shares_token"))
        batch_op.drop_index(batch_op.f("ix_collection_shares_library_id"))
        batch_op.drop_index("ix_collection_shares_collection")

    op.drop_table("collection_shares")
