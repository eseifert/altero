"""Remember login attempts across workers.

Revision ID: ae39b4d8c021
Revises: 46c9eac613f2
"""

import sqlalchemy as sa
from alembic import op

revision = "ae39b4d8c021"
down_revision = "46c9eac613f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_attempts",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available", sa.DateTime(), nullable=False),
        sa.Column("expires", sa.DateTime(), nullable=False),
        sa.Column("generation", sa.String(32), nullable=False),
    )
    op.create_index("ix_login_attempts_expires", "login_attempts", ["expires"])


def downgrade() -> None:
    op.drop_table("login_attempts")
