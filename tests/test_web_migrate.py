"""Starting a zotero.org migration from the browser.

The reading is `services/zoteroimport`, tested in `test_zotero_import.py`
against a real v3 API. What is checked here is what only this door has: a
cookie instead of a key, a CSRF token, the account password on top of both, one
migration at a time, and a request that answers before the work is done.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from altero.app import create_app
from altero.models import LibraryType
from altero.services import admin, migrations
from altero.services.auth import get_library
from altero.settings import Settings
from tests import factories
from tests.test_web_routes import PASSWORD, csrf_headers, register

SOURCE_KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"


@pytest.fixture(autouse=True)
def empty_register() -> Iterator[None]:
    """A register of its own per test; it is process-wide otherwise."""
    migrations.register = migrations.Register()
    yield
    migrations.register = migrations.Register()


@pytest.fixture
async def source(tmp_path: Path) -> AsyncIterator[FastAPI]:
    """A second server standing in for api.zotero.org, with one item in it."""
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'source.sqlite'}",
        storage_path=tmp_path / "source-storage",
    )
    application = create_app(settings)
    await application.state.database.create_all()

    async with application.state.database.session_factory() as session:
        await factories.make_user(session, user_id=4711, username="ada")
        await factories.make_api_key(session, key=SOURCE_KEY, user_id=4711)
        await session.commit()

    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://zotero.test") as client:
        response = await client.post(
            "/users/4711/items",
            headers={"Zotero-API-Key": SOURCE_KEY, "Content-Type": "application/json"},
            json=[{"itemType": "book", "title": "Moby-Dick", "key": "AAAA2345"}],
        )
        assert response.status_code == 200, response.text

    yield application
    await application.state.database.dispose()


@pytest.fixture
def reachable(source: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the migration's own HTTP client reach that server instead.

    The endpoint builds its client itself, as it must -- it outlives the
    request that started it -- so the transport is swapped rather than the
    client passed in.
    """
    from altero.api.routes import webmigrate

    original = httpx.AsyncClient

    def routed(**kwargs: Any) -> httpx.AsyncClient:
        return original(**kwargs, transport=httpx.ASGITransport(app=source))

    monkeypatch.setattr(webmigrate.httpx, "AsyncClient", routed)


@pytest.fixture
async def ada(client: httpx.AsyncClient, session: AsyncSession) -> httpx.AsyncClient:
    """One account, signed in, with a password set."""
    assert (await register(client)).status_code == 201
    return client


async def start(client: httpx.AsyncClient, **overrides: Any) -> httpx.Response:
    body: dict[str, Any] = {
        "apiKey": SOURCE_KEY,
        "currentPassword": PASSWORD,
        "replace": True,
        "server": "http://zotero.test",
    }
    body.update(overrides)
    return await client.post("/web/migrate/zotero", json=body, headers=csrf_headers(client))


async def settled(client: httpx.AsyncClient) -> dict[str, Any]:
    """Wait for the running migration to finish and return its state."""
    for _ in range(200):
        body = (await client.get("/web/migrate/zotero")).json()
        if body is not None and not body["running"]:
            return body
        await asyncio.sleep(0.02)
    raise AssertionError("the migration never finished")


class TestRunningOne:
    async def test_it_answers_before_the_work_is_done(
        self, ada: httpx.AsyncClient, reachable: None
    ) -> None:
        response = await start(ada)

        assert response.status_code == 202
        assert response.json()["running"] is True

    async def test_the_library_arrives(self, ada: httpx.AsyncClient, reachable: None) -> None:
        await start(ada)

        finished = await settled(ada)

        assert finished["error"] is None
        assert finished["summary"]["items"] == 1
        items = (await ada.get("/web/libraries/1/items")).json()
        assert [entry["data"]["title"] for entry in items["items"]] == ["Moby-Dick"]

    async def test_the_keys_and_versions_are_the_ones_zotero_org_had(
        self, ada: httpx.AsyncClient, reachable: None
    ) -> None:
        await start(ada)
        finished = await settled(ada)

        item = (await ada.get("/web/libraries/1/items/AAAA2345")).json()
        assert item["version"] == finished["summary"]["libraryVersion"]

    async def test_it_says_what_it_read(self, ada: httpx.AsyncClient, reachable: None) -> None:
        await start(ada)

        summary = (await settled(ada))["summary"]

        assert summary["username"] == "ada"
        assert summary["userID"] == 4711
        assert summary["complete"] is True

    async def test_progress_can_be_asked_for_before_anything_has_run(
        self, ada: httpx.AsyncClient
    ) -> None:
        assert (await ada.get("/web/migrate/zotero")).json() is None


class TestWhatItRefuses:
    async def test_it_needs_the_account_password(
        self, ada: httpx.AsyncClient, reachable: None
    ) -> None:
        """A session cookie is what a borrowed laptop already has."""
        response = await start(ada, currentPassword="not-the-password")

        assert response.status_code in (400, 403)
        assert (await ada.get("/web/migrate/zotero")).json() is None

    async def test_it_needs_the_csrf_token(self, ada: httpx.AsyncClient) -> None:
        response = await ada.post(
            "/web/migrate/zotero",
            json={"apiKey": SOURCE_KEY, "currentPassword": PASSWORD, "replace": True},
        )

        assert response.status_code == 403

    async def test_it_needs_a_session(self, client: httpx.AsyncClient) -> None:
        await register(client)
        headers = csrf_headers(client)
        client.cookies.delete("altero_session")

        response = await client.post(
            "/web/migrate/zotero",
            json={"apiKey": SOURCE_KEY, "currentPassword": PASSWORD},
            headers=headers,
        )

        assert response.status_code == 401

    async def test_an_api_key_does_not_open_this_door(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        key = await admin.create_api_key(session, username="ada", name="laptop")
        await session.commit()
        ada.cookies.clear()

        response = await ada.post(
            "/web/migrate/zotero",
            json={"apiKey": SOURCE_KEY, "currentPassword": PASSWORD},
            headers={"Zotero-API-Key": key.key, "X-CSRF-Token": "anything"},
        )

        assert response.status_code == 401

    async def test_an_empty_key_is_refused(self, ada: httpx.AsyncClient) -> None:
        response = await start(ada, apiKey="   ")

        assert response.status_code == 400

    async def test_a_library_with_something_in_it_needs_replace(
        self, ada: httpx.AsyncClient, session: AsyncSession, reachable: None
    ) -> None:
        """Refused up front rather than after minutes of downloading."""
        library = await get_library(session, LibraryType.USER, 1)
        item = await factories.make_item(session, library, key="LOCAL234")
        assert item is not None
        await session.commit()

        response = await start(ada, replace=False)

        assert response.status_code == 400
        assert (await ada.get("/web/migrate/zotero")).json() is None

    async def test_two_at_once_are_refused(self, ada: httpx.AsyncClient, reachable: None) -> None:
        """They would race for the same rows, and the loser is a half library."""
        first = await start(ada)
        assert first.status_code == 202

        second = await start(ada)

        assert second.status_code == 400
        await settled(ada)

    async def test_another_can_be_run_once_the_first_has_finished(
        self, ada: httpx.AsyncClient, reachable: None
    ) -> None:
        await start(ada)
        await settled(ada)

        assert (await start(ada)).status_code == 202
        await settled(ada)


class TestWhenItGoesWrong:
    async def test_a_refused_key_is_reported_rather_than_swallowed(
        self, ada: httpx.AsyncClient, reachable: None
    ) -> None:
        await start(ada, apiKey="Z" * 24)

        finished = await settled(ada)

        assert finished["error"]
        assert finished["stage"] == "failed"

    async def test_a_failure_leaves_the_library_alone(
        self, ada: httpx.AsyncClient, session: AsyncSession, reachable: None
    ) -> None:
        library = await get_library(session, LibraryType.USER, 1)
        await factories.make_item(session, library, key="LOCAL234")
        await session.commit()

        await start(ada, apiKey="Z" * 24, replace=True)
        await settled(ada)

        items = (await ada.get("/web/libraries/1/items")).json()
        assert [entry["key"] for entry in items["items"]] == ["LOCAL234"]
