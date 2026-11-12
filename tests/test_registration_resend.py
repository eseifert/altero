"""Authenticated resends share mail budgets and cannot recreate cancelled requests."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import RegistrationLimitError
from altero.models import RegistrationRequest
from altero.services import registrationaccess, registrationflow
from altero.services.mail import Message
from tests.test_registrations import NOW, POLICY


async def test_resends_are_bound_to_token_state_and_existing_mail_budgets(
    session: AsyncSession,
) -> None:
    _record, token = await registrationaccess.submit(
        session,
        username="Ada",
        email="ada@example.org",
        expires=NOW + timedelta(days=2),
        enabled=True,
        policy=POLICY,
        now=NOW,
    )
    messages: list[Message] = []

    async def send(message: Message) -> bool:
        messages.append(message)
        return True

    async def again(moment: datetime) -> None:
        await registrationflow.resend(
            session,
            token,
            policy=POLICY,
            public_url="https://trusted.example",
            send=send,
            address="127.0.0.1",
            now=moment,
        )

    await again(NOW)
    assert len(messages) == 1
    assert await registrationaccess.status(session, token, now=NOW)
    with pytest.raises(RegistrationLimitError):
        await again(NOW)
    await again(NOW + timedelta(minutes=1))
    assert len(messages) == 2
    assert await registrationaccess.cancel(session, token, now=NOW + timedelta(minutes=1))
    await again(NOW + timedelta(minutes=2))
    assert len(messages) == 2
    assert await session.scalar(select(func.count()).select_from(RegistrationRequest)) == 1


async def test_revoked_token_cannot_resend(session: AsyncSession) -> None:
    _record, token = await registrationaccess.submit(
        session,
        username="Ada",
        email="ada@example.org",
        expires=NOW + timedelta(days=2),
        enabled=True,
        policy=POLICY,
        now=NOW,
    )
    assert await registrationaccess.revoke(session, token)

    async def send(message: Message) -> bool:
        pytest.fail("A revoked applicant cannot send mail")

    await registrationflow.resend(
        session,
        token,
        policy=POLICY,
        public_url="https://trusted.example",
        send=send,
        address="127.0.0.1",
        now=NOW,
    )
