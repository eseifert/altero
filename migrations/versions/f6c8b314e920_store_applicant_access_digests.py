"""Store applicant-only token digests separately from account sessions.

Revision ID: f6c8b314e920
Revises: e4b6a192d830
"""

import sqlalchemy as sa
from alembic import op

revision = "f6c8b314e920"
down_revision = "e4b6a192d830"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("registration_requests") as batch:
        batch.add_column(sa.Column("applicant_token_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("applicant_token_expires", sa.DateTime(), nullable=True))
        batch.create_unique_constraint(
            "uq_registration_requests_applicant_token", ["applicant_token_hash"]
        )
        batch.create_check_constraint(
            "ck_registration_requests_applicant_token",
            "(applicant_token_hash IS NULL AND applicant_token_expires IS NULL) OR "
            "(applicant_token_hash IS NOT NULL AND applicant_token_expires IS NOT NULL "
            "AND applicant_token_expires > created)",
        )


def downgrade() -> None:
    with op.batch_alter_table("registration_requests") as batch:
        batch.drop_constraint("ck_registration_requests_applicant_token", type_="check")
        batch.drop_constraint("uq_registration_requests_applicant_token", type_="unique")
        batch.drop_column("applicant_token_expires")
        batch.drop_column("applicant_token_hash")
