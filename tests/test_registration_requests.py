"""Pending applicants have persistence, reservations and history, not accounts."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import Table, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from altero.db import Base

NOW = datetime(2026, 11, 9, 12)


def request_table() -> Table:
    table = Base.metadata.tables.get("registration_requests")
    assert table is not None, "Registration request model must be registered"
    return table


def test_request_metadata_contains_no_usable_credential() -> None:
    assert not {"password", "password_hash", "token"} & set(request_table().c.keys())


async def insert_request(session: AsyncSession, **changes: object) -> int:
    values = {
        "username": "Ada",
        "email": "ada@example.org",
        "reserved_username": "ada",
        "reserved_email": "ada@example.org",
        "created": NOW,
        "expires": NOW + timedelta(days=1),
        **changes,
    }
    key = await session.scalar(
        request_table().insert().values(**values).returning(request_table().c.id)
    )
    await session.commit()
    assert key is not None
    return key


async def test_an_applicant_creates_no_account_library_or_credential(session: AsyncSession) -> None:
    await insert_request(session)
    for name in ("users", "libraries", "api_keys", "web_sessions"):
        assert (
            await session.scalar(select(func.count()).select_from(Base.metadata.tables[name])) == 0
        )


@pytest.mark.parametrize("field", ["reserved_username", "reserved_email"])
async def test_pending_reservations_are_unique(session: AsyncSession, field: str) -> None:
    await insert_request(session)
    duplicate = {"reserved_username": "grace", "reserved_email": "grace@example.org"}
    duplicate[field] = "ada" if field == "reserved_username" else "ada@example.org"
    with pytest.raises(IntegrityError):
        await insert_request(session, **duplicate)
    await session.rollback()


@pytest.mark.parametrize("state", ["CANCELLED", "EXPIRED"])
async def test_terminal_history_does_not_reserve_a_name_or_address(
    session: AsyncSession, state: str
) -> None:
    for _ in range(2):
        await insert_request(session, status=state, reserved_username=None, reserved_email=None)
    await insert_request(session)
    assert await session.scalar(select(func.count()).select_from(request_table())) == 3


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "UNKNOWN"},
        {"reserved_username": None},
        {"reserved_email": None},
        {"status": "CANCELLED"},
        {"status": "REVIEW_PENDING"},
        {"email_verified": NOW},
        {"status": "APPROVED", "reserved_username": None, "reserved_email": None},
        {
            "status": "REJECTED",
            "email_verified": NOW,
            "reserved_username": None,
            "reserved_email": None,
        },
        {"user_id": 1},
        {"expires": NOW},
        {"decided_at": NOW, "decided_by": 1},
    ],
)
async def test_inconsistent_lifecycle_rows_are_rejected(
    session: AsyncSession, changes: dict[str, object]
) -> None:
    with pytest.raises(IntegrityError):
        await insert_request(session, **changes)
    await session.rollback()


async def test_decision_history_can_outlive_the_actor_and_account(session: AsyncSession) -> None:
    key = await insert_request(
        session,
        status="APPROVED",
        reserved_username=None,
        reserved_email=None,
        email_verified=NOW,
        decided_at=NOW,
        decided_by=42,
        user_id=99,
    )
    row = (await session.execute(select(request_table()).where(request_table().c.id == key))).one()
    assert row.decided_by == 42
    assert row.user_id == 99
    assert (
        await session.scalar(select(func.count()).select_from(Base.metadata.tables["users"])) == 0
    )
