"""Mailbox-first registration orchestration with durable submission/mail quotas."""

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.db import UNICODE_LOWER
from altero.errors import InvalidInputError
from altero.models import RegistrationRequest, RegistrationStatus
from altero.services import registrationaccess, registrationlimits, webauth
from altero.services.emailverify import hash_token
from altero.services.mail import Message
from altero.services.registrationpolicy import RegistrationPolicy

logger = logging.getLogger("altero.registration")
Sender = Callable[[Message], Awaitable[bool]]


def _budgets(
    address: str, recipient: str, ip_limit: int, global_limit: int
) -> tuple[registrationlimits.Budget, ...]:
    Budget = registrationlimits.Budget
    return (
        Budget("registration-submit-address-hour", address, ip_limit, timedelta(hours=1)),
        Budget("registration-submit-instance-hour", "instance", global_limit, timedelta(hours=1)),
        Budget("registration-mail-minute", recipient, 1, timedelta(minutes=1)),
        Budget("registration-mail-day", recipient, 5, timedelta(days=1)),
    )


def _link_message(public_url: str, recipient: str, proof: str) -> Message:
    return Message(
        to=recipient,
        subject="Your altero registration request",
        body=(
            "Confirm or resume your registration request on this altero server:\n\n"
            f"{public_url.rstrip('/')}/app/registration#token={proof}\n\n"
            "This link lasts at most 24 hours and can be used once. "
            "Library access requires administrator approval.\n"
        ),
    )


async def _deliver(send: Sender, message: Message) -> None:
    try:
        await send(message)
    except Exception:
        logger.warning("Registration mail delivery failed")


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
    allowed: bool = True,
    now: datetime | None = None,
) -> None:
    """Acknowledge uniformly; deliver access only through the nominated mailbox.

    No returned token or account-availability flag reaches the submitting browser.
    New, duplicate and failed-delivery cases share the same durable mail budgets.
    A matching existing request can recover even while pending capacity is full.
    """
    moment = registrationaccess._moment(now)
    username = webauth.validate_username(username)
    if len(username) > 255 or "\x00" in username:
        raise InvalidInputError("Invalid registration username")
    recipient = policy.address(email)
    await registrationlimits.reserve(
        session,
        *_budgets(address, recipient, ip_limit, global_limit),
        now=moment,
    )
    if not allowed:
        return
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
        message = _link_message(public_url, saved_recipient, token)
    else:
        saved_recipient = recipient
        body = (
            "A registration request was made using this email address. "
            "These details could not be reserved for a new application. "
            "If you already have an account, sign in or use your normal recovery process. "
            "Otherwise retry your original request details or contact the administrator. "
            "If you did not request this, you can ignore this message.\n"
        )
        message = Message(to=saved_recipient, subject="Your altero registration request", body=body)
    await _deliver(send, message)


async def resend(
    session: AsyncSession,
    token: str,
    *,
    policy: RegistrationPolicy,
    public_url: str,
    send: Sender,
    address: str,
    ip_limit: int = 5,
    global_limit: int = 100,
    now: datetime | None = None,
) -> None:
    """Resend to the current stored mailbox without ever creating an application."""
    moment = registrationaccess._moment(now)
    row = (
        await session.execute(
            select(RegistrationRequest.id, RegistrationRequest.email).where(
                RegistrationRequest.applicant_token_hash == hash_token(token),
                RegistrationRequest.applicant_token_expires > moment,
                RegistrationRequest.expires > moment,
                registrationaccess._resumable(),
            )
        )
    ).first()
    if row is None:
        return
    recipient = policy.address(row.email)
    await registrationlimits.reserve(
        session, *_budgets(address, recipient, ip_limit, global_limit), now=moment
    )
    proof = await registrationaccess.issue_mailbox_link(
        session,
        row.id,
        policy=policy,
        expected_email=recipient,
        applicant_token=token,
        now=moment,
    )
    if proof:
        await _deliver(send, _link_message(public_url, *proof))
