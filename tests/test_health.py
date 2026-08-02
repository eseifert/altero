"""The readiness check an orchestrator polls."""

from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero import API_VERSION, __version__
from altero.app import create_app
from altero.services import health
from altero.settings import Settings


@pytest.fixture
async def unreachable() -> AsyncIterator[httpx.AsyncClient]:
    """A server whose database cannot be opened at all."""
    app = create_app(Settings(database_url="sqlite+aiosqlite:////nonexistent/altero.sqlite"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    await app.state.database.dispose()


class TestHealthEndpoint:
    async def test_a_healthy_server_reports_what_it_is(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["version"] == __version__
        assert body["apiVersion"] == API_VERSION
        # Which Zotero item schema this server serves is the thing that changes
        # under an operator, so the probe reports it.
        assert isinstance(body["schemaVersion"], int)

    async def test_it_needs_no_credentials(self, client: httpx.AsyncClient) -> None:
        # A probe runs before anyone has issued a key, and an orchestrator has
        # none to offer.
        response = await client.get("/health")

        assert response.status_code == 200

    async def test_an_unreachable_database_is_a_503(self, unreachable: httpx.AsyncClient) -> None:
        # A process willing to answer is not the same as a server that is
        # ready. An orchestrator that cannot tell them apart routes traffic at
        # an instance that can serve nothing.
        response = await unreachable.get("/health")

        assert response.status_code == 503
        assert response.json()["status"] == "error"

    async def test_the_failure_names_no_internals(self, unreachable: httpx.AsyncClient) -> None:
        # /health is unauthenticated, so its body reaches anyone who can reach
        # the port; a driver error would tell them the path of the database.
        body = await unreachable.get("/health")

        assert "nonexistent" not in body.text
        assert "sqlite" not in body.text.lower()


class TestMigrationRevision:
    async def test_an_unstamped_database_reports_none(self, session: AsyncSession) -> None:
        # The suite builds its schema with create_all(), which stamps nothing.
        # Null is the honest answer; a guess would be worse than silence.
        assert await health.migration_revision(session) is None

    async def test_a_stamped_database_reports_its_revision(self, session: AsyncSession) -> None:
        from sqlalchemy import text

        await session.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        await session.execute(text("INSERT INTO alembic_version VALUES ('c1b573deea88')"))

        assert await health.migration_revision(session) == "c1b573deea88"
