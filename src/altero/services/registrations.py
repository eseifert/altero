"""Internal pending-request operations; public gated registration is not enabled.

Use a session without unrelated pending writes: these operations own their
commit/rollback boundaries. An application is not an account or a credential.
The later activation operation must check account availability again, since an
operator may provision an account while somebody has a pending reservation.
"""

from datetime import UTC, datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from altero.db import UNICODE_LOWER
from altero.errors import ForbiddenError, InvalidInputError
from altero.models import RegistrationRequest, RegistrationStatus, User
from altero.services import emailverify, webauth

PENDING = (RegistrationStatus.EMAIL_PENDING, RegistrationStatus.REVIEW_PENDING)
UNAVAILABLE = "That username or email address is unavailable"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo is None else moment.astimezone(UTC).replace(tzinfo=None)


async def _expire_due(session: AsyncSession, moment: datetime) -> int:
    keys = list(
        await session.scalars(
            update(RegistrationRequest)
            .where(RegistrationRequest.status.in_(PENDING), RegistrationRequest.expires <= moment)
            .values(status=RegistrationStatus.EXPIRED, reserved_username=None, reserved_email=None)
            .returning(RegistrationRequest.id)
        )
    )
    return len(keys)


async def expire(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Release due reservations without deleting request history."""
    count = await _expire_due(session, _utc(now or _now()))
    await session.commit()
    return count


async def submit(
    session: AsyncSession,
    *,
    username: str,
    email: str,
    expires: datetime,
    display_name: str = "",
    enabled: bool = False,
    now: datetime | None = None,
) -> RegistrationRequest:
    """Reserve an applicant's name/address, only with explicit internal opt-in.

    No public route or operator setting enables this yet. Mail verification,
    approval, admission checks and abuse budgets must be integrated first.
    """
    if not enabled:
        raise ForbiddenError("Gated registration is not enabled")
    name = webauth.validate_username(username)
    display = display_name.strip() or name
    if len(name) > 255 or len(display) > 255:
        raise InvalidInputError("Username and display name must be at most 255 characters")
    address = emailverify.normalise(email)
    if any("\x00" in value for value in (name, display, address)):
        raise InvalidInputError("Registration fields may not contain null characters")
    moment, deadline = _utc(now or _now()), _utc(expires)
    if deadline <= moment:
        raise InvalidInputError("A registration request must expire in the future")

    await expire(session, now=moment)
    # SQLite's built-in lower() folds ASCII only. Match the canonical Python
    # lower-case reservation even for an existing accented username.
    fold = (
        getattr(func, UNICODE_LOWER) if session.get_bind().dialect.name == "sqlite" else func.lower
    )
    existing = await session.scalar(
        select(User.id)
        .where(
            or_(
                fold(User.username) == name.lower(),
                fold(User.email) == address,
            )
        )
        .limit(1)
    )
    if existing is not None:
        raise InvalidInputError(UNAVAILABLE)
    record = RegistrationRequest(
        username=name,
        email=address,
        display_name=display,
        reserved_username=name.lower(),
        reserved_email=address,
        created=moment,
        expires=deadline,
    )
    session.add(record)
    try:
        await session.commit()
    except IntegrityError:
        # The unique reservation columns choose one winner across workers;
        # a pre-insert SELECT alone cannot reserve an identity.
        await session.rollback()
        raise InvalidInputError(UNAVAILABLE) from None
    return record


async def record_email_verification(
    session: AsyncSession, request_id: int, email: str, *, now: datetime | None = None
) -> bool:
    """Record a mailbox proof consumed by a trusted caller in this same session.

    The token consumer must bind its proof to this request and address. An ID
    and address supplied by an applicant are not proof. Related token-consumption
    writes commit with this transition; no public route calls this primitive yet.
    """
    address = emailverify.normalise(email)
    if "\x00" in address:
        raise InvalidInputError("Registration fields may not contain null characters")
    moment = _utc(now or _now())
    await _expire_due(session, moment)
    key = await session.scalar(
        update(RegistrationRequest)
        .where(
            RegistrationRequest.id == request_id,
            RegistrationRequest.email == address,
            RegistrationRequest.status == RegistrationStatus.EMAIL_PENDING,
            RegistrationRequest.expires > moment,
        )
        .values(status=RegistrationStatus.REVIEW_PENDING, email_verified=moment)
        .returning(RegistrationRequest.id)
    )
    await session.commit()
    return key is not None


async def cancel(session: AsyncSession, request_id: int, *, now: datetime | None = None) -> bool:
    """Cancel a live request after the caller has authenticated its applicant.

    The row ID is not an authorization. Applicant authentication belongs to the
    later status/session flow; no public route calls this primitive yet.
    """
    moment = _utc(now or _now())
    await _expire_due(session, moment)
    key = await session.scalar(
        update(RegistrationRequest)
        .where(
            RegistrationRequest.id == request_id,
            RegistrationRequest.status.in_(PENDING),
            RegistrationRequest.expires > moment,
        )
        .values(status=RegistrationStatus.CANCELLED, reserved_username=None, reserved_email=None)
        .returning(RegistrationRequest.id)
    )
    await session.commit()
    return key is not None
