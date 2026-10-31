"""Finish verified SAML with the browser session.

Revision ID: 46c9eac613f2
Revises: e5b8c1f07a26
"""

import sqlalchemy as sa
from alembic import op

revision = "46c9eac613f2"
down_revision = "e5b8c1f07a26"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("auth_requests", sa.Column("verified_saml", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("auth_requests") as batch_op:
        batch_op.drop_column("verified_saml")
