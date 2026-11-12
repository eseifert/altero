"""Mailbox links renew applicant access only after proof is consumed."""

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import RegistrationStatus
from altero.services import registrationaccess, registrationadmission
from tests.test_registration_review import reviewer
from tests.test_registrations import NOW, POLICY


async def link(session: AsyncSession, key: int):  # type: ignore[no-untyped-def]
    function = getattr(registrationaccess, "issue_mailbox_link", None)
    assert callable(function), "Mailbox-bound applicant resumption must be implemented"
    return await function(session, key, policy=POLICY, now=NOW)


async def claim(session: AsyncSession, proof: str) -> str | None:
    return await registrationaccess.claim_mailbox(session, proof, policy=POLICY, now=NOW)


async def test_mailbox_proof_claims_applicant_access_once(session: AsyncSession) -> None:
    record, initial = await registrationaccess.submit(
        session,
        username="Ada",
        email="ada@example.org",
        expires=NOW + timedelta(days=2),
        enabled=True,
        policy=POLICY,
        now=NOW,
    )
    recipient, proof = await link(session, record.id)
    assert recipient == record.email
    assert await registrationaccess.status(session, proof, now=NOW) is None
    token = await claim(session, proof)
    assert token
    assert await registrationaccess.status(session, initial, now=NOW) is None
    assert await claim(session, proof) is None
    state = await registrationaccess.status(session, token, now=NOW)
    assert state
    assert state.status == RegistrationStatus.REVIEW_PENDING


async def test_recovery_link_does_not_revoke_a_working_cookie_until_consumed(
    session: AsyncSession,
) -> None:
    record, _initial = await registrationaccess.submit(
        session,
        username="Ada",
        email="ada@example.org",
        expires=NOW + timedelta(days=2),
        enabled=True,
        policy=POLICY,
        now=NOW,
    )
    _, proof = await link(session, record.id)
    first = await claim(session, proof)
    assert first
    _, recovery = await link(session, record.id)
    assert await registrationaccess.status(session, first, now=NOW)
    second = await claim(session, recovery)
    assert second
    assert await registrationaccess.status(session, first, now=NOW) is None


async def test_approved_passwordless_applicant_can_resume_but_enrolled_account_cannot(
    session: AsyncSession,
) -> None:
    actor = await reviewer(session)
    record, _ = await registrationaccess.submit(
        session,
        username="Ada",
        email="ada@example.org",
        expires=NOW + timedelta(days=2),
        enabled=True,
        policy=POLICY,
        now=NOW,
    )
    _, proof = await link(session, record.id)
    token = await claim(session, proof)
    assert token
    assert await registrationadmission.approve(
        session, record.id, actor_id=actor.id, policy=POLICY, now=NOW
    )
    _, recovery = await link(session, record.id)
    recovered = await claim(session, recovery)
    assert recovered
    assert await registrationadmission.enroll(
        session, recovered, "an uncommon very long enrollment password", now=NOW
    )
    await session.refresh(record)
    assert await link(session, record.id) is None


async def test_expired_proof_and_changed_address_cannot_claim_access(session: AsyncSession) -> None:
    record, _ = await registrationaccess.submit(
        session,
        username="Ada",
        email="ada@example.org",
        expires=NOW + timedelta(days=3),
        enabled=True,
        policy=POLICY,
        now=NOW,
    )
    _, proof = await link(session, record.id)
    assert (
        await registrationaccess.claim_mailbox(
            session, proof, policy=POLICY, now=NOW + timedelta(days=1)
        )
        is None
    )
    record.email = record.reserved_email = "changed@example.org"
    await session.commit()
    assert await claim(session, proof) is None
