"""Let an administrator issue a password-reset link

Revision ID: fb5251b1453e
Revises: c665a433b31d
Create Date: 2026-08-11 19:50:35.639089

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fb5251b1453e"
down_revision: str | Sequence[str] | None = "c665a433b31d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "password_resets",
        sa.Column("id", sa.Integer(), nullable=False),
        # Only the digest of the token in the link, so a copy of this table
        # sets nobody's password.
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("issued_by", sa.Integer(), nullable=True),
        sa.Column(
            "created",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("expires", sa.DateTime(), nullable=False),
        # The issuer may be deleted later; the record of the reset survives it.
        sa.ForeignKeyConstraint(["issued_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("password_resets", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_password_resets_expires"), ["expires"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_password_resets_token_hash"), ["token_hash"], unique=True
        )
        batch_op.create_index(batch_op.f("ix_password_resets_user_id"), ["user_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("password_resets", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_password_resets_user_id"))
        batch_op.drop_index(batch_op.f("ix_password_resets_token_hash"))
        batch_op.drop_index(batch_op.f("ix_password_resets_expires"))

    op.drop_table("password_resets")
