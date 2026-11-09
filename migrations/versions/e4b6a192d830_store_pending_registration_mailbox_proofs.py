"""Store pending registration mailbox proofs without raw tokens.

Revision ID: e4b6a192d830
Revises: d2a9e41f670b
"""

import sqlalchemy as sa
from alembic import op

revision = "e4b6a192d830"
down_revision = "d2a9e41f670b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("registration_requests") as batch:
        batch.add_column(sa.Column("email_token_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("email_token_address", sa.String(320), nullable=True))
        batch.add_column(sa.Column("email_token_expires", sa.DateTime(), nullable=True))
        batch.create_unique_constraint("uq_registration_requests_email_token", ["email_token_hash"])
        batch.create_check_constraint(
            "ck_registration_requests_email_token",
            "(email_token_hash IS NULL AND email_token_address IS NULL "
            "AND email_token_expires IS NULL) OR "
            "(status = 'EMAIL_PENDING' AND email_token_hash IS NOT NULL "
            "AND email_token_address IS NOT NULL AND email_token_expires IS NOT NULL "
            "AND email_token_expires > created AND email_token_expires <= expires)",
        )


def downgrade() -> None:
    with op.batch_alter_table("registration_requests") as batch:
        batch.drop_constraint("ck_registration_requests_email_token", type_="check")
        batch.drop_constraint("uq_registration_requests_email_token", type_="unique")
        batch.drop_column("email_token_expires")
        batch.drop_column("email_token_address")
        batch.drop_column("email_token_hash")
