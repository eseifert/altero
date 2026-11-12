"""Applicant tokens are separate from account credentials and mailbox proofs."""

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_registration_requests import NOW, insert_request, request_table


def test_applicant_token_metadata_is_paired_and_unique() -> None:
    table = request_table()
    assert {"applicant_token_hash", "applicant_token_expires"} <= set(table.c.keys())
    assert any(c.name == "uq_registration_requests_applicant_token" for c in table.constraints)


@pytest.mark.parametrize(
    "changes",
    [
        {"applicant_token_hash": "a" * 64},
        {"applicant_token_expires": NOW + timedelta(days=1)},
        {"applicant_token_hash": "a" * 64, "applicant_token_expires": NOW},
    ],
)
async def test_incomplete_or_invalid_applicant_tokens_are_rejected(
    session: AsyncSession,
    changes: dict[str, object],
) -> None:
    with pytest.raises(IntegrityError):
        await insert_request(session, **changes)
    await session.rollback()


async def test_applicant_token_can_outlive_the_request_deadline(session: AsyncSession) -> None:
    key = await insert_request(
        session, applicant_token_hash="a" * 64, applicant_token_expires=NOW + timedelta(days=7)
    )
    assert (
        await session.scalar(
            select(request_table().c.applicant_token_hash).where(request_table().c.id == key)
        )
        == "a" * 64
    )
    with pytest.raises(IntegrityError):
        await insert_request(
            session,
            username="Other",
            email="other@example.org",
            reserved_username="other",
            reserved_email="other@example.org",
            applicant_token_hash="a" * 64,
            applicant_token_expires=NOW + timedelta(days=7),
        )
    await session.rollback()
