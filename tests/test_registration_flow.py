"""Mailbox-first submission is budgeted and discloses no account availability."""

import importlib
import importlib.util
from datetime import timedelta
from types import ModuleType

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import RegistrationLimitError
from altero.models import RegistrationRequest
from altero.services import admin, registrationaccess
from altero.services.mail import Message
from tests.test_registrations import NOW, POLICY


def flow() -> ModuleType:
    assert importlib.util.find_spec("altero.services.registrationflow"), (
        "Budgeted mailbox-first registration must be implemented"
    )
    return importlib.import_module("altero.services.registrationflow")


async def test_submission_emails_only_saved_mailbox_and_claims_no_browser_access(
    session: AsyncSession,
) -> None:
    messages: list[Message] = []

    async def send(message: Message) -> bool:
        messages.append(message)
        return True

    result = await flow().submit(
        session,
        username="Ada",
        email=" ADA@EXAMPLE.ORG ",
        policy=POLICY,
        public_url="https://trusted.example",
        send=send,
        address="127.0.0.1",
        now=NOW,
    )
    assert result is None
    assert len(messages) == 1
    assert messages[0].to == "ada@example.org"
    assert "https://trusted.example/app/registration#token=" in messages[0].body
    proof = messages[0].body.split("#token=")[1].split()[0]
    assert await registrationaccess.claim_mailbox(session, proof, policy=POLICY, now=NOW)


async def test_existing_account_gets_the_same_acknowledgment_and_no_new_request(
    session: AsyncSession,
) -> None:
    user = await admin.create_user(session, username="Ada")
    user.email = "ada@example.org"
    await session.commit()
    messages: list[Message] = []

    async def send(message: Message) -> bool:
        messages.append(message)
        return True

    assert (
        await flow().submit(
            session,
            username="Ada",
            email="ada@example.org",
            policy=POLICY,
            public_url="https://trusted.example",
            send=send,
            address="127.0.0.1",
            now=NOW,
        )
        is None
    )
    assert len(messages) == 1
    assert "#token=" not in messages[0].body
    assert await session.scalar(select(func.count()).select_from(RegistrationRequest)) == 0


async def test_failed_delivery_can_be_retried_under_the_same_recipient_budgets(
    session: AsyncSession,
) -> None:
    messages: list[Message] = []

    async def send(message: Message) -> bool:
        messages.append(message)
        return False

    options = dict(
        username="Ada",
        email="ada@example.org",
        policy=POLICY,
        public_url="https://trusted.example",
        send=send,
        address="127.0.0.1",
    )
    await flow().submit(session, **options, now=NOW)
    with pytest.raises(RegistrationLimitError):
        await flow().submit(session, **options, now=NOW)
    await flow().submit(session, **options, now=NOW + timedelta(minutes=1))
    assert len(messages) == 2
    assert await session.scalar(select(func.count()).select_from(RegistrationRequest)) == 1


async def test_existing_request_can_resume_while_capacity_is_full(session: AsyncSession) -> None:
    messages: list[Message] = []

    async def send(message: Message) -> bool:
        messages.append(message)
        return True

    options = dict(
        username="Ada",
        email="ada@example.org",
        policy=POLICY,
        public_url="https://trusted.example",
        send=send,
        address="127.0.0.1",
        max_pending=1,
    )
    await flow().submit(session, **options, now=NOW)
    await flow().submit(session, **options, now=NOW + timedelta(minutes=1))
    assert len(messages) == 2
    assert all("#token=" in message.body for message in messages)


async def test_recipient_snapshot_prevents_mail_redirection_after_budgeting(
    session: AsyncSession,
) -> None:
    from tests.test_registrations import submit

    record = await submit(session)
    record.email = record.reserved_email = "changed@example.org"
    await session.commit()
    assert (
        await registrationaccess.issue_mailbox_link(
            session, record.id, policy=POLICY, expected_email="ada@example.org", now=NOW
        )
        is None
    )
