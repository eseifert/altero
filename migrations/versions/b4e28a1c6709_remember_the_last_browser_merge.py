"""Remember the last browser merge.

Revision ID: b4e28a1c6709
Revises: 64a2c9d7e301
"""

import sqlalchemy as sa
from alembic import op

revision = "b4e28a1c6709"
down_revision = "64a2c9d7e301"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "merge_undos",
        sa.Column(
            "library_id",
            sa.Integer(),
            sa.ForeignKey("libraries.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("patches", sa.JSON(), nullable=False),
        sa.Column("expires", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_merge_undos_user_id", "merge_undos", ["user_id"])
    op.create_index("ix_merge_undos_expires", "merge_undos", ["expires"])


def downgrade() -> None:
    op.drop_table("merge_undos")
