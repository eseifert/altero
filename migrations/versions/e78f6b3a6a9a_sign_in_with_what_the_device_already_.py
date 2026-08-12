"""Sign in with what the device already checked

Revision ID: e78f6b3a6a9a
Revises: 94c7e9cd27a7
Create Date: 2026-08-12 11:04:15.519311

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e78f6b3a6a9a"
down_revision: str | Sequence[str] | None = "94c7e9cd27a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # A public key and a counter: there is no secret stored here, which is the
    # whole point of a passkey. The challenge table is separate because the
    # sign-in half has no session to hang one on -- it starts with nobody
    # claiming to be anybody.
    op.create_table(
        "passkey_credentials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("credential_id", sa.String(length=255), nullable=False),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column("sign_count", sa.Integer(), nullable=False),
        sa.Column("transports", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("backed_up", sa.Boolean(), nullable=False),
        sa.Column(
            "created", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("last_used", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("passkey_credentials", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_passkey_credentials_credential_id"), ["credential_id"], unique=True
        )
        batch_op.create_index(
            batch_op.f("ix_passkey_credentials_user_id"), ["user_id"], unique=False
        )

    op.create_table(
        "webauthn_challenges",
        sa.Column("challenge", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("purpose", sa.String(length=8), nullable=False),
        sa.Column(
            "created", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("expires", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("challenge"),
    )
    with op.batch_alter_table("webauthn_challenges", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_webauthn_challenges_expires"), ["expires"], unique=False
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("webauthn_challenges", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_webauthn_challenges_expires"))

    op.drop_table("webauthn_challenges")
    with op.batch_alter_table("passkey_credentials", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_passkey_credentials_user_id"))
        batch_op.drop_index(batch_op.f("ix_passkey_credentials_credential_id"))

    op.drop_table("passkey_credentials")
