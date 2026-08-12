"""Speak SAML to a directory that speaks nothing else

Revision ID: 94c7e9cd27a7
Revises: f78e07c7b67d
Create Date: 2026-08-12 10:13:49.013116

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "94c7e9cd27a7"
down_revision: str | Sequence[str] | None = "f78e07c7b67d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Its own table rather than a flag on auth_requests: the request is spent
    # the moment the browser comes back, while an assertion id has to be
    # remembered until the assertion could no longer be replayed.
    op.create_table(
        "consumed_assertions",
        sa.Column("assertion_id", sa.String(length=255), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column(
            "consumed", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("expires", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["identity_providers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("assertion_id"),
    )
    with op.batch_alter_table("consumed_assertions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_consumed_assertions_expires"), ["expires"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_consumed_assertions_provider_id"), ["provider_id"], unique=False
        )

    with op.batch_alter_table("identity_providers", schema=None) as batch_op:
        batch_op.add_column(sa.Column("idp_entity_id", sa.String(length=255), nullable=False))
        batch_op.add_column(sa.Column("sso_url", sa.String(length=500), nullable=False))
        batch_op.add_column(sa.Column("certificates", sa.Text(), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("identity_providers", schema=None) as batch_op:
        batch_op.drop_column("certificates")
        batch_op.drop_column("sso_url")
        batch_op.drop_column("idp_entity_id")

    with op.batch_alter_table("consumed_assertions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_consumed_assertions_provider_id"))
        batch_op.drop_index(batch_op.f("ix_consumed_assertions_expires"))

    op.drop_table("consumed_assertions")
