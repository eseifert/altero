"""Changing the policy cannot leave older requests exempt from eligibility."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError
from altero.models import RegistrationStatus
from altero.services import registrations
from tests.test_registration_email import consume, issue, token_for
from tests.test_registration_policy import policy
from tests.test_registrations import NOW, submit


async def test_opt_in_alone_cannot_bypass_the_policy(session: AsyncSession) -> None:
    with pytest.raises(ForbiddenError):
        await submit(session, policy=None)


async def test_submission_checks_domain_before_reserving_an_identity(session: AsyncSession) -> None:
    with pytest.raises(ForbiddenError):
        await submit(session, policy=policy("elsewhere.example"))
    assert (await submit(session)).username == "Ada"


async def test_issue_rechecks_the_current_policy_without_replacing_an_existing_link(
    session: AsyncSession,
) -> None:
    record = await submit(session)
    token = await token_for(session, record)
    assert await issue(session, record.id, policy=policy("elsewhere.example")) is None
    assert await consume(session, token)


async def test_consumption_rechecks_policy_without_spending_an_ineligible_proof(
    session: AsyncSession,
) -> None:
    record = await submit(session)
    token = await token_for(session, record)
    assert not await consume(session, token, policy=policy("elsewhere.example"))
    await session.refresh(record)
    assert record.status == RegistrationStatus.EMAIL_PENDING
    assert record.email_token_hash
    assert await consume(session, token)


@pytest.mark.parametrize("operation", ["issue", "consume"])
async def test_mailbox_operations_require_an_explicit_policy(
    session: AsyncSession, operation: str
) -> None:
    record = await submit(session)
    token = await token_for(session, record)
    attempt = (
        issue(session, record.id, policy=None)
        if operation == "issue"
        else consume(session, token, policy=None)
    )
    with pytest.raises(ForbiddenError):
        await attempt
    assert await consume(session, token)


async def test_a_subdomain_must_be_explicitly_allowed_at_each_stage(session: AsyncSession) -> None:
    record = await submit(session, email="ada@dept.example.org")
    assert await issue(session, record.id, policy=policy("example.org")) is None
    issued = await issue(session, record.id, policy=policy("dept.example.org"))
    assert issued
    assert not await consume(session, issued[1], policy=policy("example.org"))
    assert await consume(session, issued[1], policy=policy("dept.example.org"))


async def test_trusted_verification_recording_also_enforces_eligibility(
    session: AsyncSession,
) -> None:
    record = await submit(session)
    with pytest.raises(ForbiddenError):
        await registrations.record_email_verification(
            session, record.id, record.email, now=NOW, policy=policy("elsewhere.example")
        )
    await session.refresh(record)
    assert record.status == RegistrationStatus.EMAIL_PENDING
