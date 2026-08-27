"""Add OAuth2 and OIDC tables

Revision ID: a1b2c3d4e5f6
Revises: e78f6b3a6a9a
Create Date: 2026-08-27 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "8b8fe12270c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "oauth_clients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("client_secret_hash", sa.String(length=128), nullable=True),
        sa.Column("client_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("redirect_uris", sa.Text(), nullable=False, server_default=""),
        sa.Column("allowed_scopes", sa.String(length=255), nullable=False, server_default="openid profile library.read library.write annotations.read annotations.write files.read"),
        sa.Column("is_confidential", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("disabled_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("oauth_clients", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_oauth_clients_client_id"), ["client_id"], unique=True)

    op.create_table(
        "oauth_authorization_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("redirect_uri", sa.String(length=500), nullable=False),
        sa.Column("scopes", sa.String(length=255), nullable=False),
        sa.Column("code_challenge", sa.String(length=128), nullable=False),
        sa.Column("code_challenge_method", sa.String(length=16), nullable=False, server_default="S256"),
        sa.Column("nonce", sa.String(length=128), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("created", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("oauth_authorization_codes", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_oauth_authorization_codes_code_hash"), ["code_hash"], unique=True)
        batch_op.create_index(batch_op.f("ix_oauth_authorization_codes_client_id"), ["client_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_oauth_authorization_codes_user_id"), ["user_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_oauth_authorization_codes_expires_at"), ["expires_at"], unique=False)

    op.create_table(
        "oauth_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token_type", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("family_id", sa.String(length=64), nullable=True),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("scopes", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("oauth_tokens", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_oauth_tokens_token_hash"), ["token_hash"], unique=True)
        batch_op.create_index(batch_op.f("ix_oauth_tokens_family_id"), ["family_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_oauth_tokens_client_id"), ["client_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_oauth_tokens_user_id"), ["user_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_oauth_tokens_expires_at"), ["expires_at"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("oauth_tokens")
    op.drop_table("oauth_authorization_codes")
    op.drop_table("oauth_clients")
