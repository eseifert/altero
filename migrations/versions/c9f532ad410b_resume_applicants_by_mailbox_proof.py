"""Allow mailbox-proof resumption before first-password enrollment.

Revision ID: c9f532ad410b
Revises: b8e421fc309a
"""

from alembic import op

revision = "c9f532ad410b"
down_revision = "b8e421fc309a"
branch_labels = None
depends_on = None


def _constraint(states: str) -> str:
    return (
        "(email_token_hash IS NULL AND email_token_address IS NULL "
        "AND email_token_expires IS NULL) OR "
        f"(status IN ({states}) AND email_token_hash IS NOT NULL "
        "AND email_token_address IS NOT NULL AND email_token_expires IS NOT NULL "
        "AND email_token_expires > created AND email_token_expires <= expires)"
    )


def _replace(states: str) -> None:
    with op.batch_alter_table(
        "registration_requests", table_kwargs={"sqlite_autoincrement": True}
    ) as batch:
        batch.drop_constraint("ck_registration_requests_email_token", type_="check")
        batch.create_check_constraint("ck_registration_requests_email_token", _constraint(states))


def upgrade() -> None:
    _replace("'EMAIL_PENDING', 'REVIEW_PENDING', 'APPROVED'")


def downgrade() -> None:
    op.execute(
        "UPDATE registration_requests SET email_token_hash=NULL, "
        "email_token_address=NULL, email_token_expires=NULL WHERE status != 'EMAIL_PENDING'"
    )
    _replace("'EMAIL_PENDING'")
