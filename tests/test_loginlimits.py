"""Durable admission before checking a guess, shared by independent workers."""

import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.db import Database
from altero.errors import LoginBackoffError
from altero.models import LoginAttempt
from altero.services import loginlimits

NOW = datetime(2026, 10, 31, 12)


async def attempt(
    session: AsyncSession,
    *,
    account: str = "user:1",
    address: str = "192.0.2.1",
    stage: str = "password",
    now: datetime = NOW,
) -> loginlimits.Admission:
    return await loginlimits.reserve(
        session, account=account, address=address, stage=stage, now=now
    )


async def test_backoff_doubles_is_capped_and_does_not_extend_on_refusal(
    session: AsyncSession,
) -> None:
    moment = NOW
    for number in range(1, 20):
        await attempt(session, now=moment)
        delay = 0 if number < 5 else min(300, 2 ** (number - 5))
        if delay:
            with pytest.raises(LoginBackoffError) as refused:
                await attempt(session, now=moment + timedelta(microseconds=1))
            assert refused.value.retry_after == delay
            moment += timedelta(seconds=delay)
    # The exact boundary admits the next attempt, including after repeated 429s.
    await attempt(session, now=moment)


async def test_account_limit_survives_changing_addresses(session: AsyncSession) -> None:
    for number in range(5):
        await attempt(session, address=f"192.0.2.{number}")
    with pytest.raises(LoginBackoffError):
        await attempt(session, address="198.51.100.1")


async def test_address_limit_survives_changing_accounts_and_stages(session: AsyncSession) -> None:
    for number in range(20):
        await attempt(
            session, account=f"unknown:{number}", stage="factor" if number % 2 else "password"
        )
    with pytest.raises(LoginBackoffError):
        await attempt(session, account="another")


async def test_a_refusal_charges_neither_bucket(session: AsyncSession) -> None:
    for _ in range(5):
        await attempt(session)
    with pytest.raises(LoginBackoffError):
        await attempt(session, address="198.51.100.1")
    # A rejected account must not leave an address row behind.
    assert await session.scalar(select(func.count()).select_from(LoginAttempt)) == 2


async def test_success_clears_only_its_account_and_stage(session: AsyncSession) -> None:
    factor = await attempt(session, stage="factor")
    password = await attempt(session)
    await loginlimits.succeed(session, password)
    rows = list(await session.scalars(select(LoginAttempt)))
    assert len(rows) == 2  # address and the outstanding second factor
    assert any(row.key == factor.key for row in rows)
    # Success refunds itself, but cannot launder the address's other attempts.
    for number in range(18):
        await attempt(session, account=f"user:{number + 2}")
    admitted = await attempt(session, account="user:100")
    await loginlimits.succeed(session, admitted)
    await attempt(session, account="user:101")
    with pytest.raises(LoginBackoffError):
        await attempt(session, account="user:102")


async def test_success_refunds_only_its_address_reservation(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(loginlimits, "_now", lambda: NOW)
    for _ in range(30):
        admitted = await attempt(session)
        await loginlimits.succeed(session, admitted)
    rows = list(await session.scalars(select(LoginAttempt)))
    assert len(rows) == 1
    assert rows[0].attempts == 0


async def test_late_success_cannot_refund_a_new_address_window(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(loginlimits, "_now", lambda: NOW)
    old = await attempt(session)
    later = NOW + timedelta(minutes=15)
    for number in range(20):
        await attempt(session, account=f"new:{number}", now=later)
    await loginlimits.succeed(session, old)
    with pytest.raises(LoginBackoffError):
        await attempt(session, account="new:100", now=later)


async def test_an_older_success_cannot_clear_a_newer_attempt(session: AsyncSession) -> None:
    older = await attempt(session)
    for _ in range(4):
        await attempt(session)
    await loginlimits.succeed(session, older)
    with pytest.raises(LoginBackoffError):
        await attempt(session)


async def test_idle_records_expire_and_are_pruned(session: AsyncSession) -> None:
    for _ in range(5):
        await attempt(session)
    await attempt(session, account="new", address="new", now=NOW + timedelta(minutes=15))
    assert await session.scalar(select(func.count()).select_from(LoginAttempt)) == 2
    await attempt(session, now=NOW + timedelta(minutes=15))


async def test_identifiers_and_addresses_are_not_stored_verbatim(session: AsyncSession) -> None:
    await attempt(session, account="unknown:private@example.org")
    rows = list(await session.scalars(select(LoginAttempt)))
    assert all(len(row.key) == 64 for row in rows)
    assert all("private" not in row.key and "192.0.2.1" not in row.key for row in rows)


async def assert_shared_budget(database: Database) -> None:
    """Two pools and many concurrent admissions still spend one allowance."""

    async def reserve_one() -> bool:
        async with database.session_factory() as session:
            try:
                await attempt(session)
            except LoginBackoffError:
                return False
            return True

    results = await asyncio.gather(*(reserve_one() for _ in range(12)))
    assert sum(results) == 5


async def test_parallel_requests_share_one_budget(app: FastAPI) -> None:
    await assert_shared_budget(app.state.database)


async def test_new_pool_still_observes_the_backoff(app: FastAPI) -> None:
    async with app.state.database.session_factory() as session:
        for _ in range(5):
            await attempt(session)
    other = Database(app.state.settings)
    try:
        async with other.session_factory() as session:
            with pytest.raises(LoginBackoffError):
                await attempt(session)
    finally:
        await other.dispose()
