"""Hold pending registration requests separately from accounts.

Revision ID: d2a9e41f670b
Revises: c8f17a2d904e
"""

import sqlalchemy as sa
from alembic import op

revision = "d2a9e41f670b"
down_revision = "c8f17a2d904e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "registration_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "EMAIL_PENDING",
                "REVIEW_PENDING",
                "APPROVED",
                "REJECTED",
                "CANCELLED",
                "EXPIRED",
                native_enum=False,
                create_constraint=True,
                name="registrationstatus",
            ),
            nullable=False,
            server_default="EMAIL_PENDING",
        ),
        sa.Column("created", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("expires", sa.DateTime(), nullable=False),
        sa.Column("reserved_username", sa.String(255), nullable=True),
        sa.Column("reserved_email", sa.String(320), nullable=True),
        sa.Column("email_verified", sa.DateTime(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("decided_by", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.UniqueConstraint("reserved_username", name="uq_registration_requests_username"),
        sa.UniqueConstraint("reserved_email", name="uq_registration_requests_email"),
        sa.CheckConstraint(
            "(status IN ('EMAIL_PENDING', 'REVIEW_PENDING') "
            "AND reserved_username IS NOT NULL AND reserved_email IS NOT NULL) OR "
            "(status NOT IN ('EMAIL_PENDING', 'REVIEW_PENDING') "
            "AND reserved_username IS NULL AND reserved_email IS NULL)",
            name="ck_registration_requests_reservations",
        ),
        sa.CheckConstraint(
            "(status = 'EMAIL_PENDING' AND email_verified IS NULL) OR "
            "(status IN ('REVIEW_PENDING', 'APPROVED', 'REJECTED') "
            "AND email_verified IS NOT NULL) OR status IN ('CANCELLED', 'EXPIRED')",
            name="ck_registration_requests_verification",
        ),
        sa.CheckConstraint(
            "(status IN ('APPROVED', 'REJECTED') "
            "AND decided_at IS NOT NULL AND decided_by IS NOT NULL) OR "
            "(status NOT IN ('APPROVED', 'REJECTED') "
            "AND decided_at IS NULL AND decided_by IS NULL)",
            name="ck_registration_requests_decision",
        ),
        sa.CheckConstraint(
            "(status = 'APPROVED' AND user_id IS NOT NULL) OR "
            "(status != 'APPROVED' AND user_id IS NULL)",
            name="ck_registration_requests_activation",
        ),
        sa.CheckConstraint("expires > created", name="ck_registration_requests_lifetime"),
    )
    op.create_index("ix_registration_requests_expires", "registration_requests", ["expires"])
    op.create_index(
        "ix_registration_requests_status_created", "registration_requests", ["status", "created"]
    )


def downgrade() -> None:
    op.drop_table("registration_requests")
