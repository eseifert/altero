"""Applicant-only credentials; never account sessions or library authorization."""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, case, or_, select, true, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from altero.errors import InvalidInputError
from altero.models import RegistrationRequest, RegistrationStatus, User
from altero.services import registrations
from altero.services.emailverify import hash_token
from altero.services.registrationpolicy import RegistrationPolicy
from altero.services.registrations import PENDING

LIFETIME = timedelta(days=7)


def _moment(now: datetime | None) -> datetime:
    value = now or datetime.now(UTC)
    return value if value.tzinfo is None else value.astimezone(UTC).replace(tzinfo=None)


@dataclass(frozen=True, slots=True)
class ApplicantStatus:
    request_id: int
    status: RegistrationStatus
    expires: datetime


async def submit(
    session: AsyncSession,
    *,
    username: str,
    email: str,
    expires: datetime,
    display_name: str = "",
    enabled: bool = False,
    policy: RegistrationPolicy | None = None,
    max_pending: int = 1000,
    now: datetime | None = None,
) -> tuple[RegistrationRequest, str]:
    """Commit a new application and its initial applicant credential together.

    Return the raw token only after commit; failures roll back the reservation,
    credential and expiry cleanup. A future route must deliver it only to the
    submitting browser. No public registration switch or route uses this yet.
    """
    moment = _moment(now)
    try:
        record = await registrations.prepare_submission(
            session,
            username=username,
            email=email,
            expires=expires,
            display_name=display_name,
            enabled=enabled,
            policy=policy,
            max_pending=max_pending,
            now=moment,
        )
        token = secrets.token_urlsafe(32)
        record.applicant_token_hash = hash_token(token)
        record.applicant_token_expires = moment + LIFETIME
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise InvalidInputError(registrations.UNAVAILABLE) from None
    except Exception:
        await session.rollback()
        raise
    return record, token


async def issue(
    session: AsyncSession, request_id: int, *, now: datetime | None = None
) -> str | None:
    """Replace a live request's credential for an already authorized caller.

    A row ID grants no authority to call this. Initial credentials belong to
    submit(), which commits them with the reservation. This replacement helper
    requires prior applicant authentication; no public caller exists yet. The
    raw token is returned once; only its digest is persisted.
    """
    moment = _moment(now)
    token = secrets.token_urlsafe(32)
    key = await session.scalar(
        update(RegistrationRequest)
        .where(
            RegistrationRequest.id == request_id,
            RegistrationRequest.status.in_(PENDING),
            RegistrationRequest.created <= moment,
            RegistrationRequest.expires > moment,
        )
        .values(applicant_token_hash=hash_token(token), applicant_token_expires=moment + LIFETIME)
        .returning(RegistrationRequest.id)
    )
    await session.commit()
    return token if key is not None else None


async def status(
    session: AsyncSession, token: str | None, *, now: datetime | None = None
) -> ApplicantStatus | None:
    """Read only the presented credential's outcome, without committing writes."""
    if not token:
        return None
    moment = _moment(now)
    row = (
        await session.execute(
            select(
                RegistrationRequest.id, RegistrationRequest.status, RegistrationRequest.expires
            ).where(
                RegistrationRequest.applicant_token_hash == hash_token(token),
                RegistrationRequest.applicant_token_expires > moment,
            )
        )
    ).one_or_none()
    if row is None:
        return None
    state = row.status
    if state in PENDING and row.expires <= moment:
        state = RegistrationStatus.EXPIRED
    return ApplicantStatus(row.id, state, row.expires)


async def cancel(session: AsyncSession, token: str | None, *, now: datetime | None = None) -> bool:
    """Authorize and cancel in one write, retaining the token for outcome reads."""
    if not token:
        return False
    moment = _moment(now)
    key = await session.scalar(
        update(RegistrationRequest)
        .where(
            RegistrationRequest.applicant_token_hash == hash_token(token),
            RegistrationRequest.applicant_token_expires > moment,
            RegistrationRequest.status.in_(PENDING),
            RegistrationRequest.expires > moment,
        )
        .values(
            status=RegistrationStatus.CANCELLED,
            reserved_username=None,
            reserved_email=None,
            email_token_hash=None,
            email_token_address=None,
            email_token_expires=None,
        )
        .returning(RegistrationRequest.id)
    )
    await session.commit()
    return key is not None


async def revoke(session: AsyncSession, token: str | None) -> bool:
    """Clear the presented credential without altering application history."""
    if not token:
        return False
    key = await session.scalar(
        update(RegistrationRequest)
        .where(RegistrationRequest.applicant_token_hash == hash_token(token))
        .values(applicant_token_hash=None, applicant_token_expires=None)
        .returning(RegistrationRequest.id)
    )
    await session.commit()
    return key is not None


def _resumable() -> ColumnElement[bool]:
    account = (
        select(User.id)
        .where(
            User.id == RegistrationRequest.user_id,
            User.email == RegistrationRequest.email,
            User.password_hash.is_(None),
            User.disabled_at.is_(None),
        )
        .exists()
    )
    return or_(
        RegistrationRequest.status.in_(PENDING),
        and_(
            RegistrationRequest.status == RegistrationStatus.APPROVED,
            account,
        ),
    )


async def issue_mailbox_link(
    session: AsyncSession,
    request_id: int,
    *,
    policy: RegistrationPolicy,
    expected_email: str | None = None,
    applicant_token: str | None = None,
    now: datetime | None = None,
) -> tuple[str, str] | None:
    """Return stored recipient/proof after the caller reserves delivery budgets.

    Issuing mail never revokes an existing applicant cookie. Only consumption
    of proof delivered to the saved mailbox replaces that credential.
    """
    moment = _moment(now)
    proof = secrets.token_urlsafe(32)
    recipient = await session.scalar(
        update(RegistrationRequest)
        .where(
            RegistrationRequest.id == request_id,
            RegistrationRequest.expires > moment,
            RegistrationRequest.email == expected_email if expected_email is not None else true(),
            and_(
                RegistrationRequest.applicant_token_hash == hash_token(applicant_token),
                RegistrationRequest.applicant_token_expires > moment,
            )
            if applicant_token is not None
            else true(),
            _resumable(),
            registrations._eligible(policy),
        )
        .values(
            email_token_hash=hash_token(proof),
            email_token_address=RegistrationRequest.email,
            email_token_expires=case(
                (
                    RegistrationRequest.expires < moment + registrations.EMAIL_PROOF_LIFETIME,
                    RegistrationRequest.expires,
                ),
                else_=moment + registrations.EMAIL_PROOF_LIFETIME,
            ),
        )
        .returning(RegistrationRequest.email_token_address)
    )
    await session.commit()
    return (recipient, proof) if recipient else None


async def claim_mailbox(
    session: AsyncSession,
    proof: str,
    *,
    policy: RegistrationPolicy,
    now: datetime | None = None,
) -> str | None:
    """Atomically spend an address-bound link and renew applicant-only access."""
    if not proof:
        return None
    moment = _moment(now)
    token = secrets.token_urlsafe(32)
    key = await session.scalar(
        update(RegistrationRequest)
        .where(
            RegistrationRequest.email_token_hash == hash_token(proof),
            RegistrationRequest.email_token_address == RegistrationRequest.email,
            RegistrationRequest.email_token_expires > moment,
            RegistrationRequest.expires > moment,
            _resumable(),
            registrations._eligible(policy),
        )
        .values(
            status=case(
                (
                    RegistrationRequest.status == RegistrationStatus.EMAIL_PENDING,
                    RegistrationStatus.REVIEW_PENDING.name,
                ),
                else_=RegistrationRequest.status,
            ),
            email_verified=case(
                (RegistrationRequest.email_verified.is_(None), moment),
                else_=RegistrationRequest.email_verified,
            ),
            applicant_token_hash=hash_token(token),
            applicant_token_expires=moment + LIFETIME,
            **registrations._CLEAR_EMAIL_TOKEN,
        )
        .returning(RegistrationRequest.id)
    )
    await session.commit()
    return token if key is not None else None
