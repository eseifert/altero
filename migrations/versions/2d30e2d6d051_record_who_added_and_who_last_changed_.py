"""Record who added and who last changed each item

Revision ID: 2d30e2d6d051
Revises: c7042cfd41ce
Create Date: 2026-08-05 16:38:37.439332

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2d30e2d6d051"
down_revision: str | Sequence[str] | None = "c7042cfd41ce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Both columns are nullable, which is the setting and not merely what makes
    the upgrade possible: every item that already exists was written before
    anybody was recorded, and guessing an author for it would be worse than
    saying nothing. They fill in as items are next written.

    The constraints are named rather than left to autogenerate's ``None``.
    SQLite rebuilds the table and does not care, but PostgreSQL cannot drop an
    anonymous constraint, so the downgrade below would be unrunnable there.
    """
    with op.batch_alter_table("items", schema=None) as batch_op:
        batch_op.add_column(sa.Column("created_by_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("last_modified_by_user_id", sa.Integer(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_items_created_by_user_id"), ["created_by_user_id"], unique=False
        )
        batch_op.create_foreign_key(
            "fk_items_created_by_user_id",
            "users",
            ["created_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_items_last_modified_by_user_id",
            "users",
            ["last_modified_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("items", schema=None) as batch_op:
        batch_op.drop_constraint("fk_items_last_modified_by_user_id", type_="foreignkey")
        batch_op.drop_constraint("fk_items_created_by_user_id", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_items_created_by_user_id"))
        batch_op.drop_column("last_modified_by_user_id")
        batch_op.drop_column("created_by_user_id")
