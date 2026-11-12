"""Applicant-only credentials; never account sessions or library authorization."""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import InvalidInputError
from altero.models import RegistrationRequest, RegistrationStatus
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
