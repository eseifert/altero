"""The operator's screens, and who is refused them.

Two lines are held here. Only an instance administrator gets in — enumerated
from the router itself, so a route added later is covered without anybody
having to remember this file. And an administrator counts and measures without
reading: nothing under /web/admin answers with an item, a title or a file.
"""

import httpx
import pytest
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from altero.api.routes import webadmin
from altero.services import admin, webauth
from tests.factories import make_item
from tests.test_web_routes import PASSWORD, csrf_headers, register

#: Every route the operator's screens expose, as (method, path).
ADMIN_ROUTES = [
    (method, route.path)
    for route in webadmin.router.routes
    if isinstance(route, APIRoute)
    for method in sorted((route.methods or set()) - {"HEAD", "OPTIONS"})
]


async def sign_in_as_somebody_else(client: httpx.AsyncClient, session: AsyncSession) -> None:
    """Register the administrator, then sign in as an ordinary account."""
    await register(client)
    grace = await admin.create_user(session, username="grace")
    await webauth.set_password(session, grace, PASSWORD)
    await client.post("/web/auth/login", json={"username": "grace", "password": PASSWORD})


class TestWhoGetsIn:
    def test_there_is_something_to_check(self) -> None:
        """A router that lost its routes would pass every test below."""
        assert ADMIN_ROUTES

    @pytest.mark.parametrize(("method", "path"), ADMIN_ROUTES)
    async def test_an_ordinary_account_is_refused_every_route(
        self, client: httpx.AsyncClient, session: AsyncSession, method: str, path: str
    ) -> None:
        await sign_in_as_somebody_else(client, session)

        response = await client.request(
            method, path.format(user_id=1), headers=csrf_headers(client), json={}
        )

        assert response.status_code == 403

    @pytest.mark.parametrize(("method", "path"), ADMIN_ROUTES)
    async def test_a_stranger_is_refused_every_route(
        self, client: httpx.AsyncClient, method: str, path: str
    ) -> None:
        response = await client.request(method, path.format(user_id=1), json={})

        assert response.status_code == 401

    @pytest.mark.parametrize(("method", "path"), ADMIN_ROUTES)
    async def test_an_api_key_is_refused_every_route(
        self, client: httpx.AsyncClient, session: AsyncSession, method: str, path: str
    ) -> None:
        """The instance's own screens are not a second door into the v3 API.

        A key is what a sync client holds; it authenticates nothing here, and
        the administrator flag is not a grant a key can carry.
        """
        await register(client)
        key = await admin.create_api_key(session, username="ada", name="laptop")
        client.cookies.clear()

        response = await client.request(
            method, path.format(user_id=1), headers={"Zotero-API-Key": key.key}, json={}
        )

        assert response.status_code == 401


class TestTheOverview:
    async def test_it_reports_what_the_instance_is_running(self, client: httpx.AsyncClient) -> None:
        """ "Which migration is this instance on" is the upgrade's question."""
        await register(client)

        body = (await client.get("/web/admin/overview")).json()

        assert body["version"]
        assert body["apiVersion"] == 3
        assert "revision" in body
        assert body["database"] == "sqlite"

    async def test_it_never_reports_the_database_url(self, client: httpx.AsyncClient) -> None:
        """It carries a password, and the dialect is the whole of the answer."""
        await register(client)

        body = await (await client.get("/web/admin/overview")).aread()

        assert b"sqlite+aiosqlite" not in body

    async def test_it_counts_the_accounts_and_libraries(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        await admin.create_user(session, username="grace")

        body = (await client.get("/web/admin/overview")).json()

        assert body["users"] == 2
        assert body["libraries"] == 2


class TestTheStorageReport:
    async def test_it_lists_every_library_with_what_it_holds(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        library = await admin.list_libraries(session)
        await make_item(session, library[0], fields={"title": "Notes on the Analytical Engine"})

        body = (await client.get("/web/admin/storage")).json()

        (entry,) = body["libraries"]
        assert entry["type"] == "user"
        assert entry["ownerId"] == 1
        assert entry["items"] == 1

    async def test_it_reports_nominal_against_real(self, client: httpx.AsyncClient) -> None:
        """The number zotero.org cannot report; see services/storagestats.py."""
        await register(client)

        body = (await client.get("/web/admin/storage")).json()

        assert body["nominalBytes"] == 0
        assert body["realBytes"] == 0
        assert body["savedBytes"] == 0

    async def test_it_does_not_name_a_single_item(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """An administrator counts and measures. They do not read.

        The flag says who runs the instance, not who may read what is in it,
        and a storage report that leaked a title would make it both.
        """
        await register(client)
        library = await admin.list_libraries(session)
        await make_item(session, library[0], fields={"title": "Notes on the Analytical Engine"})

        body = await (await client.get("/web/admin/storage")).aread()

        assert b"Analytical Engine" not in body


class TestPurgingStorage:
    """The only route in this layer that removes bytes."""

    async def test_it_takes_the_administrator_s_own_password(
        self, client: httpx.AsyncClient
    ) -> None:
        await register(client)

        response = await client.post(
            "/web/admin/storage/purge",
            json={"currentPassword": "not it"},
            headers=csrf_headers(client),
        )

        assert response.status_code == 403

    async def test_it_reports_what_it_freed(self, client: httpx.AsyncClient) -> None:
        await register(client)

        response = await client.post(
            "/web/admin/storage/purge",
            json={"currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        assert response.status_code == 200
        assert response.json() == {"files": 0, "bytes": 0}
