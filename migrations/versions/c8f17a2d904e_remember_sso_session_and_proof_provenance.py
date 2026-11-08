"""Remember SSO session and proof provenance.

Revision ID: c8f17a2d904e
Revises: b4e28a1c6709
"""

import sqlalchemy as sa
from alembic import op

revision = "c8f17a2d904e"
down_revision = "b4e28a1c6709"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "web_sessions",
        sa.Column("sso_authenticated", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("web_sessions", sa.Column("sso_reauthenticated", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("web_sessions") as batch:
        batch.drop_column("sso_reauthenticated")
        batch.drop_column("sso_authenticated")
