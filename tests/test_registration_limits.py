"""Registration/mail budgets persist across workers and charge atomically."""

import asyncio
import importlib
import importlib.util
from datetime import timedelta
from types import ModuleType

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import RegistrationLimitError
from altero.models import RegistrationBudget
from tests.test_registrations import NOW


def limits() -> ModuleType:
    assert importlib.util.find_spec("altero.services.registrationlimits"), (
        "Durable registration budgets must be implemented"
    )
    return importlib.import_module("altero.services.registrationlimits")


async def test_shared_window_expires_at_its_exact_deadline(app: FastAPI) -> None:
    service = limits()
    budget = service.Budget("mail-hour", "ada@example.org", 2, timedelta(hours=1))
    for _ in range(2):
        async with app.state.database.session_factory() as session:
            await service.reserve(session, budget, now=NOW)
    async with app.state.database.session_factory() as session:
        with pytest.raises(service.RegistrationLimitError) as caught:
            await service.reserve(session, budget, now=NOW + timedelta(minutes=1))
        assert caught.value.retry_after == 3540
        await service.reserve(session, budget, now=NOW + timedelta(hours=1))


async def test_refused_multi_bucket_reservation_charges_neither_bucket(
    session: AsyncSession,
) -> None:
    service = limits()
    full = service.Budget("recipient", "ada@example.org", 1, timedelta(hours=1))
    other = service.Budget("address", "127.0.0.1", 1, timedelta(hours=1))
    await service.reserve(session, full, now=NOW)
    with pytest.raises(service.RegistrationLimitError):
        await service.reserve(session, other, full, now=NOW)
    await service.reserve(session, other, now=NOW)


async def test_concurrent_workers_cannot_overspend(app: FastAPI) -> None:
    service = limits()
    budget = service.Budget("mail-hour", "ada@example.org", 2, timedelta(hours=1))

    async def worker() -> bool:
        async with app.state.database.session_factory() as session:
            try:
                await service.reserve(session, budget, now=NOW)
            except service.RegistrationLimitError:
                return False
            return True

    assert sum(await asyncio.gather(*(worker() for _ in range(4)))) == 2


async def test_failed_budget_commit_rolls_back_without_charging(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = limits()
    budget = service.Budget("mail", "private@example.org", 1, timedelta(hours=1))

    async def fail() -> None:
        raise RuntimeError("Injected commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(session, "commit", fail)
        with pytest.raises(RuntimeError, match="Injected"):
            await service.reserve(session, budget, now=NOW)
    assert await session.scalar(select(func.count()).select_from(RegistrationBudget)) == 0
    await service.reserve(session, budget, now=NOW)
    stored = await session.scalar(select(RegistrationBudget))
    assert stored is not None
    assert len(stored.key) == 64
    assert "private" not in stored.key


async def test_budget_exhaustion_is_429_with_retry_after(
    app: FastAPI,
    client: httpx2.AsyncClient,
) -> None:
    async def exhausted() -> None:
        raise RegistrationLimitError(60)

    app.add_api_route("/web/test-registration-limit", exhausted)
    response = await client.get("/web/test-registration-limit")
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
