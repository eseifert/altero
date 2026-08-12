"""Take a second factor as a code sent by mail

Revision ID: d0692313b4cf
Revises: f4210015f742
Create Date: 2026-08-12 07:58:30.827526

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d0692313b4cf"
down_revision: str | Sequence[str] | None = "f4210015f742"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # A row and nothing else: the address and whether it has been proved are
    # already on the user, and a copy here could disagree with them.
    op.create_table(
        "email_factors",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )
    # Cascaded from the session rather than from the user: a code answers one
    # sign-in, and ending that sign-in must take the code with it.
    op.create_table(
        "login_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column(
            "created",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("expires", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["web_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("login_codes", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_login_codes_code_hash"), ["code_hash"], unique=False)
        batch_op.create_index(batch_op.f("ix_login_codes_expires"), ["expires"], unique=False)
        batch_op.create_index(batch_op.f("ix_login_codes_session_id"), ["session_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("login_codes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_login_codes_session_id"))
        batch_op.drop_index(batch_op.f("ix_login_codes_expires"))
        batch_op.drop_index(batch_op.f("ix_login_codes_code_hash"))

    op.drop_table("login_codes")
    op.drop_table("email_factors")
