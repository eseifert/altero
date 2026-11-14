"""Let operators trust OIDC email verification.

Revision ID: 79be412c6a05
Revises: c9f532ad410b
"""

import sqlalchemy as sa
from alembic import op

revision = "79be412c6a05"
down_revision = "c9f532ad410b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "identity_providers",
        sa.Column("trust_email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    with op.batch_alter_table("identity_providers") as batch_op:
        batch_op.drop_column("trust_email_verified")
