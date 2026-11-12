"""Applicants awaiting admission, separate from users and library credentials."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, Enum, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from altero.db import Base


class RegistrationStatus(StrEnum):
    EMAIL_PENDING = "email_pending"
    REVIEW_PENDING = "review_pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class RegistrationRequest(Base):
    """Admission history with unique reservations only while awaiting a decision.

    An ID identifies a row; it proves no identity and authenticates no request.
    No password, account session, library or library credential belongs to an applicant.
    The public gated-registration workflow is not enabled yet.
    """

    __tablename__ = "registration_requests"
    __table_args__ = (
        UniqueConstraint("reserved_username", name="uq_registration_requests_username"),
        UniqueConstraint("reserved_email", name="uq_registration_requests_email"),
        UniqueConstraint("email_token_hash", name="uq_registration_requests_email_token"),
        UniqueConstraint("applicant_token_hash", name="uq_registration_requests_applicant_token"),
        CheckConstraint(
            "(applicant_token_hash IS NULL AND applicant_token_expires IS NULL) OR "
            "(applicant_token_hash IS NOT NULL AND applicant_token_expires IS NOT NULL "
            "AND applicant_token_expires > created)",
            name="ck_registration_requests_applicant_token",
        ),
        CheckConstraint(
            "(email_token_hash IS NULL AND email_token_address IS NULL "
            "AND email_token_expires IS NULL) OR "
            "(status = 'EMAIL_PENDING' AND email_token_hash IS NOT NULL "
            "AND email_token_address IS NOT NULL AND email_token_expires IS NOT NULL "
            "AND email_token_expires > created AND email_token_expires <= expires)",
            name="ck_registration_requests_email_token",
        ),
        CheckConstraint(
            "(status IN ('EMAIL_PENDING', 'REVIEW_PENDING') "
            "AND reserved_username IS NOT NULL AND reserved_email IS NOT NULL) OR "
            "(status NOT IN ('EMAIL_PENDING', 'REVIEW_PENDING') "
            "AND reserved_username IS NULL AND reserved_email IS NULL)",
            name="ck_registration_requests_reservations",
        ),
        CheckConstraint(
            "(status = 'EMAIL_PENDING' AND email_verified IS NULL) OR "
            "(status IN ('REVIEW_PENDING', 'APPROVED', 'REJECTED') "
            "AND email_verified IS NOT NULL) OR status IN ('CANCELLED', 'EXPIRED')",
            name="ck_registration_requests_verification",
        ),
        CheckConstraint(
            "(status IN ('APPROVED', 'REJECTED') "
            "AND decided_at IS NOT NULL AND decided_by IS NOT NULL) OR "
            "(status NOT IN ('APPROVED', 'REJECTED') "
            "AND decided_at IS NULL AND decided_by IS NULL)",
            name="ck_registration_requests_decision",
        ),
        CheckConstraint(
            "(status = 'APPROVED' AND user_id IS NOT NULL) OR "
            "(status != 'APPROVED' AND user_id IS NULL)",
            name="ck_registration_requests_activation",
        ),
        CheckConstraint("expires > created", name="ck_registration_requests_lifetime"),
        Index("ix_registration_requests_status_created", "status", "created"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[RegistrationStatus] = mapped_column(
        Enum(
            RegistrationStatus, native_enum=False, create_constraint=True, name="registrationstatus"
        ),
        default=RegistrationStatus.EMAIL_PENDING,
        server_default="EMAIL_PENDING",
    )
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires: Mapped[datetime] = mapped_column(DateTime, index=True)
    #: Canonical name/address, cleared on every terminal transition. Separate
    #: from the original fields so audit history cannot squat on either value.
    reserved_username: Mapped[str | None] = mapped_column(String(255), default=None)
    reserved_email: Mapped[str | None] = mapped_column(String(320), default=None)
    email_verified: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    #: One outstanding mailbox proof, never the raw link token. The address
    #: snapshot prevents an old link from verifying a later address change.
    email_token_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    email_token_address: Mapped[str | None] = mapped_column(String(320), default=None)
    email_token_expires: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    #: A separate applicant-only credential. It never identifies an account,
    #: and may outlive the application deadline to report a terminal outcome.
    applicant_token_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    applicant_token_expires: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    #: Historical IDs, deliberately not foreign keys: deleting an administrator
    #: or an admitted account must not erase who made the admission decision.
    #: Neither value is an authority to authenticate or access a library.
    decided_by: Mapped[int | None] = mapped_column(default=None)
    user_id: Mapped[int | None] = mapped_column(default=None)
