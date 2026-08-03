"""Refusing a client that asks too often.

The desktop client understands two headers, and both must be whole seconds or
it ignores them. ``Zotero.Sync.APIClient._checkRetry`` logs
"Invalid Retry-After delay" and gives up on anything that fails
``parseInt(retryAfter) != retryAfter``; the ``Backoff`` handler has the same
guard and pauses its caller for that many seconds.

Off unless configured. A personal server with one user has nothing to throttle,
and a limit nobody asked for turns a working sync into a stuck one.
"""

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from altero.app import create_app
from altero.services.ratelimit import RateLimiter
from altero.settings import Settings
from tests.factories import make_api_key, make_user

KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"
OTHER_KEY = "Q8MjGpzMfAv3cAOwwvRQEXte"
AUTH = {"Zotero-API-Key": KEY}


class TestTheLimiter:
    """The counting itself, which knows nothing about HTTP."""

    def test_requests_within_the_allowance_are_let_through(self) -> None:
        clock = FakeClock()
        limiter = RateLimiter(limit=3, window=60, now=clock)

        assert [limiter.check("someone") for _ in range(3)] == [None, None, None]

    def test_the_next_one_is_told_how_long_to_wait(self) -> None:
        clock = FakeClock()
        limiter = RateLimiter(limit=2, window=60, now=clock)
        limiter.check("someone")
        limiter.check("someone")

        assert limiter.check("someone") == 60

    def test_the_wait_counts_down_within_the_window(self) -> None:
        clock = FakeClock()
        limiter = RateLimiter(limit=1, window=60, now=clock)
        limiter.check("someone")
        clock.advance(45)

        assert limiter.check("someone") == 15

    def test_a_wait_is_never_reported_as_zero(self) -> None:
        # The client multiplies by 1000 and pauses; zero would be no pause at
        # all, and it would come straight back to another 429.
        clock = FakeClock()
        limiter = RateLimiter(limit=1, window=60, now=clock)
        limiter.check("someone")
        clock.advance(59.9)

        assert limiter.check("someone") == 1

    def test_the_window_resets(self) -> None:
        clock = FakeClock()
        limiter = RateLimiter(limit=1, window=60, now=clock)
        limiter.check("someone")
        clock.advance(61)

        assert limiter.check("someone") is None

    def test_callers_are_counted_apart(self) -> None:
        clock = FakeClock()
        limiter = RateLimiter(limit=1, window=60, now=clock)
        limiter.check("someone")

        assert limiter.check("someone else") is None

    def test_a_limit_of_zero_means_no_limit(self) -> None:
        clock = FakeClock()
        limiter = RateLimiter(limit=0, window=60, now=clock)

        assert [limiter.check("someone") for _ in range(50)] == [None] * 50

    def test_lapsed_callers_are_forgotten(self) -> None:
        # Otherwise the table grows with every key and IP ever seen.
        clock = FakeClock()
        limiter = RateLimiter(limit=5, window=60, now=clock)
        for caller in range(20):
            limiter.check(f"caller-{caller}")
        clock.advance(61)
        limiter.check("someone")

        assert limiter.tracked() == 1


class FakeClock:
    """A clock the tests move by hand."""

    def __init__(self) -> None:
        self.time = 1000.0

    def advance(self, seconds: float) -> None:
        self.time += seconds

    def __call__(self) -> float:
        return self.time


@pytest.fixture
async def limited(session: AsyncSession, tmp_path_factory: pytest.TempPathFactory) -> FastAPI:
    """An application that allows two requests per minute."""
    path = tmp_path_factory.mktemp("limited") / "test.sqlite"
    application = create_app(
        Settings(database_url=f"sqlite+aiosqlite:///{path}", rate_limit=2, rate_limit_window=60)
    )
    await application.state.database.create_all()
    async with application.state.database.session_factory() as setup:
        await make_user(setup, user_id=1)
        await make_api_key(setup, key=KEY, user_id=1)
        await make_api_key(setup, key=OTHER_KEY, user_id=1, name="second")
    return application


async def get(app: FastAPI, path: str, headers: dict[str, str] | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path, headers=headers or {})


class TestOverHttp:
    async def test_nothing_is_limited_by_default(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await make_user(session, user_id=1)
        await make_api_key(session, key=KEY, user_id=1)

        for _ in range(30):
            response = await client.get("/users/1/items", headers=AUTH)

        assert response.status_code == 200

    async def test_an_over_eager_client_gets_429(self, limited: FastAPI) -> None:
        for _ in range(2):
            await get(limited, "/users/1/items", AUTH)

        response = await get(limited, "/users/1/items", AUTH)

        assert response.status_code == 429

    async def test_the_delay_is_whole_seconds(self, limited: FastAPI) -> None:
        # The client compares parseInt(value) against the value and discards
        # anything that does not match, so "59.7" would be thrown away.
        for _ in range(2):
            await get(limited, "/users/1/items", AUTH)

        response = await get(limited, "/users/1/items", AUTH)

        retry_after = response.headers["Retry-After"]
        assert retry_after.isdigit()
        assert int(retry_after) >= 1

    async def test_two_keys_do_not_share_an_allowance(self, limited: FastAPI) -> None:
        for _ in range(2):
            await get(limited, "/users/1/items", AUTH)

        response = await get(limited, "/users/1/items", {"Zotero-API-Key": OTHER_KEY})

        assert response.status_code == 200

    async def test_the_health_probe_is_never_limited(self, limited: FastAPI) -> None:
        # An orchestrator polls it on a fixed interval and would take the
        # instance out of service for answering 429.
        for _ in range(10):
            response = await get(limited, "/health")

        assert response.status_code == 200
