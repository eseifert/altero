"""Accept a sign-in from somebody elses directory

Revision ID: f78e07c7b67d
Revises: d0692313b4cf
Create Date: 2026-08-12 09:33:23.885743

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f78e07c7b67d"
down_revision: str | Sequence[str] | None = "d0692313b4cf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "identity_providers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("display_name", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("issuer", sa.String(length=255), nullable=False),
        sa.Column("client_id", sa.String(length=255), nullable=False),
        sa.Column("client_secret", sa.Text(), nullable=False),
        sa.Column("scopes", sa.String(length=255), nullable=False),
        sa.Column("authorization_endpoint", sa.String(length=500), nullable=False),
        sa.Column("token_endpoint", sa.String(length=500), nullable=False),
        sa.Column("userinfo_endpoint", sa.String(length=500), nullable=False),
        sa.Column("discovered", sa.DateTime(), nullable=True),
        sa.Column("username_claim", sa.String(length=64), nullable=False),
        sa.Column("name_claim", sa.String(length=64), nullable=False),
        sa.Column("email_claim", sa.String(length=64), nullable=False),
        sa.Column("create_accounts", sa.Boolean(), nullable=False),
        sa.Column("required_claim", sa.String(length=64), nullable=False),
        sa.Column("required_value", sa.String(length=255), nullable=False),
        sa.Column("revoke_keys_on_loss", sa.Boolean(), nullable=False),
        sa.Column(
            "created", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("identity_providers", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_identity_providers_slug"), ["slug"], unique=True)

    op.create_table(
        "auth_requests",
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("code_verifier", sa.String(length=128), nullable=False),
        sa.Column("nonce", sa.String(length=64), nullable=False),
        sa.Column("next_path", sa.String(length=500), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("purpose", sa.String(length=8), nullable=False),
        sa.Column(
            "created", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("expires", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["identity_providers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("state"),
    )
    with op.batch_alter_table("auth_requests", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_auth_requests_expires"), ["expires"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_auth_requests_provider_id"), ["provider_id"], unique=False
        )

    op.create_table(
        "federated_identities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("asserted_name", sa.String(length=255), nullable=False),
        sa.Column(
            "linked", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("last_seen", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["provider_id"], ["identity_providers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_id", "subject", name="uq_identity_subject"),
    )
    with op.batch_alter_table("federated_identities", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_federated_identities_provider_id"), ["provider_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_federated_identities_user_id"), ["user_id"], unique=False
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("federated_identities", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_federated_identities_user_id"))
        batch_op.drop_index(batch_op.f("ix_federated_identities_provider_id"))

    op.drop_table("federated_identities")
    with op.batch_alter_table("auth_requests", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_auth_requests_provider_id"))
        batch_op.drop_index(batch_op.f("ix_auth_requests_expires"))

    op.drop_table("auth_requests")
    with op.batch_alter_table("identity_providers", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_identity_providers_slug"))

    op.drop_table("identity_providers")
