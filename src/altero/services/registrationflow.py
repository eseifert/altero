"""Mailbox-first registration orchestration with durable submission/mail quotas."""

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.db import UNICODE_LOWER
from altero.errors import InvalidInputError
from altero.models import RegistrationRequest, RegistrationStatus
from altero.services import registrationaccess, registrationlimits
from altero.services.mail import Message
from altero.services.registrationpolicy import RegistrationPolicy

logger = logging.getLogger("altero.registration")
Sender = Callable[[Message], Awaitable[bool]]


async def _existing(
    session: AsyncSession, username: str, email: str, moment: datetime
) -> int | None:
    fold = (
        getattr(func, UNICODE_LOWER) if session.get_bind().dialect.name == "sqlite" else func.lower
    )
    return await session.scalar(
        select(RegistrationRequest.id)
        .where(
            fold(RegistrationRequest.username) == username.strip().lower(),
            RegistrationRequest.email == email,
            RegistrationRequest.expires > moment,
            RegistrationRequest.status.in_(
                (
                    RegistrationStatus.EMAIL_PENDING,
                    RegistrationStatus.REVIEW_PENDING,
                    RegistrationStatus.APPROVED,
                )
            ),
        )
        .limit(1)
    )


async def submit(
    session: AsyncSession,
    *,
    username: str,
    email: str,
    policy: RegistrationPolicy,
    public_url: str,
    send: Sender,
    address: str,
    display_name: str = "",
    max_pending: int = 1000,
    ip_limit: int = 5,
    global_limit: int = 100,
    now: datetime | None = None,
) -> None:
    """Acknowledge uniformly; deliver access only through the nominated mailbox.

    No returned token or account-availability flag reaches the submitting browser.
    New, duplicate and failed-delivery cases share the same durable mail budgets.
    A matching existing request can recover even while pending capacity is full.
    """
    moment = registrationaccess._moment(now)
    recipient = policy.address(email)
    Budget = registrationlimits.Budget
    await registrationlimits.reserve(
        session,
        Budget("registration-submit-address-hour", address, ip_limit, timedelta(hours=1)),
        Budget("registration-submit-instance-hour", "instance", global_limit, timedelta(hours=1)),
        Budget("registration-mail-minute", recipient, 1, timedelta(minutes=1)),
        Budget("registration-mail-day", recipient, 5, timedelta(days=1)),
        now=moment,
    )
    request_id = await _existing(session, username, recipient, moment)
    if request_id is None:
        try:
            record, _token = await registrationaccess.submit(
                session,
                username=username,
                email=recipient,
                display_name=display_name,
                enabled=True,
                policy=policy,
                now=moment,
                expires=moment + timedelta(days=7),
                max_pending=max_pending,
            )
            request_id = record.id
        except InvalidInputError:
            request_id = await _existing(session, username, recipient, moment)
    proof = (
        None
        if request_id is None
        else await registrationaccess.issue_mailbox_link(
            session,
            request_id,
            policy=policy,
            expected_email=recipient,
            now=moment,
        )
    )
    if proof:
        saved_recipient, token = proof
        body = (
            "Confirm or resume your registration request on this altero server:\n\n"
            f"{public_url.rstrip('/')}/app/registration#token={token}\n\n"
            "This link lasts at most 24 hours and can be used once. "
            "An administrator must approve your request before you can use a library.\n"
        )
    else:
        saved_recipient = recipient
        body = (
            "A registration request was made using this email address. "
            "These details could not be reserved for a new application. "
            "If you already have an account, sign in or use your normal recovery process. "
            "Otherwise retry your original request details or contact the administrator. "
            "If you did not request this, you can ignore this message.\n"
        )
    try:
        await send(
            Message(to=saved_recipient, subject="Your altero registration request", body=body)
        )
    except Exception:
        # Delivery may have succeeded even when its acknowledgement was lost.
        # Do not undo the proof or refund a mailbox budget, and never log links.
        logger.warning("Registration mail delivery failed")
