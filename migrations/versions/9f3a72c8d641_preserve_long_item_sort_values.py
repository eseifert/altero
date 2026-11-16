"""Preserve long titles and free-form dates in derived sort values.

Revision ID: 9f3a72c8d641
Revises: 79be412c6a05
"""

import sqlalchemy as sa
from alembic import op

revision = "9f3a72c8d641"
down_revision = "79be412c6a05"
branch_labels = None
depends_on = None

SORT_LENGTHS = {"sort_title": 500, "sort_date": 32}


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        # TEXT alone is insufficient: an incompressible title can exceed
        # PostgreSQL's B-tree entry limit even though the table accepts it.
        for column in SORT_LENGTHS:
            op.drop_index(f"ix_items_library_{column}", table_name="items")
    with op.batch_alter_table("items") as batch_op:
        for column, length in SORT_LENGTHS.items():
            batch_op.alter_column(column, existing_type=sa.String(length), type_=sa.Text())


def downgrade() -> None:
    # PostgreSQL refuses a downgrade if stored values no longer fit. Do not
    # truncate user data or sort keys to make it succeed.
    with op.batch_alter_table("items") as batch_op:
        for column, length in SORT_LENGTHS.items():
            batch_op.alter_column(column, existing_type=sa.Text(), type_=sa.String(length))
    if op.get_bind().dialect.name == "postgresql":
        for column in SORT_LENGTHS:
            op.create_index(f"ix_items_library_{column}", "items", ["library_id", column])
