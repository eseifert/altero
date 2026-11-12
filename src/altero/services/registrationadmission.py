"""Atomic admission decisions; applicants have no account until approval commits."""

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from altero.db import UNICODE_LOWER
from altero.errors import ForbiddenError, InvalidInputError
from altero.models import Library, LibraryType, RegistrationRequest, RegistrationStatus, User
from altero.services import registrationlimits, registrations
from altero.services.registrationpolicy import RegistrationPolicy


async def approve(
    session: AsyncSession,
    request_id: int,
    *,
    actor_id: int,
    policy: RegistrationPolicy,
    now: datetime | None = None,
) -> int | None:
    """Recheck reviewer, mailbox policy and identity availability before admission.

    Account, personal library, released reservations and decision share one
    transaction. The account is never an administrator and has no password yet;
    only its authenticated applicant may complete credential enrollment later.
    The future route must authenticate its reviewer and check CSRF.
    """
    moment = registrations._utc(now or registrations._now())
    try:
        await registrationlimits.lock_capacity(session)
        if await session.scalar(registrations._reviewer_query(actor_id).with_for_update()) is None:
            raise ForbiddenError("Only a current administrator can review registration")
        await registrations._expire_due(session, moment)
        record = await session.scalar(
            select(RegistrationRequest)
            .where(
                RegistrationRequest.id == request_id,
                RegistrationRequest.status == RegistrationStatus.REVIEW_PENDING,
                RegistrationRequest.expires > moment,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if record is None:
            await session.commit()
            return None
        address = policy.address(record.email)
        fold = (
            getattr(func, UNICODE_LOWER)
            if session.get_bind().dialect.name == "sqlite"
            else func.lower
        )
        existing = await session.scalar(
            select(User.id)
            .where(
                or_(
                    fold(User.username) == record.username.lower(),
                    fold(User.email) == address,
                )
            )
            .limit(1)
        )
        if existing is not None:
            raise InvalidInputError(registrations.UNAVAILABLE)
        highest = await session.scalar(select(func.max(User.id)))
        user = User(
            id=(highest or 0) + 1,
            username=record.username,
            display_name=record.display_name,
            email=address,
            email_verified=record.email_verified,
            administrator=False,
        )
        session.add(user)
        await session.flush()
        session.add(
            Library(type=LibraryType.USER, owner_id=user.id, name=user.display_name, version=0)
        )
        record.status = RegistrationStatus.APPROVED
        record.decided_by, record.decided_at, record.user_id = actor_id, moment, user.id
        record.reserved_username = record.reserved_email = None
        await session.commit()
        return user.id
    except IntegrityError:
        await session.rollback()
        raise InvalidInputError(registrations.UNAVAILABLE) from None
    except Exception:
        await session.rollback()
        raise
