"""Persist registration and mail budgets.

Revision ID: a7d931bc205e
Revises: f6c8b314e920
"""

import sqlalchemy as sa
from alembic import op

revision = "a7d931bc205e"
down_revision = "f6c8b314e920"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "registration_budgets",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("used", sa.Integer(), nullable=False),
        sa.Column("expires", sa.DateTime(), nullable=False),
        sa.CheckConstraint("used > 0", name="ck_registration_budgets_used"),
    )
    op.create_index("ix_registration_budgets_expires", "registration_budgets", ["expires"])


def downgrade() -> None:
    op.drop_table("registration_budgets")
