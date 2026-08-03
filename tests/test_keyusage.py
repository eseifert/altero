"""Recording when and where an API key was last used.

This exists to answer one question in the key list: which of these can I
revoke? A key with no recorded use, or one last seen a year ago from an address
nobody recognises, is a key to remove.

It is deliberately not an audit log. A syncing client makes a great many
requests and writing on each would put a write in front of every read, so a key
is touched at most once per interval -- and immediately when the address
changes, because that is the part somebody would want to see straight away.
"""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import ApiKey
from altero.services import admin, keyusage


class TestTheService:
    async def test_it_records_the_time_address_and_client(self, session: AsyncSession) -> None:
        await admin.create_user(session, username="ada")
        key = await admin.create_api_key(session, username="ada", name="laptop")

        await keyusage.record(session, key.id, address="192.0.2.10", user_agent="Zotero/7.0")

        await session.refresh(key)
        assert key.last_used is not None
        assert key.last_address == "192.0.2.10"
        assert key.last_user_agent == "Zotero/7.0"

    async def test_a_second_use_within_the_interval_is_not_written(
        self, session: AsyncSession
    ) -> None:
        """Otherwise every request in a sync is also a write."""
        await admin.create_user(session, username="ada")
        key = await admin.create_api_key(session, username="ada", name="laptop")
        await keyusage.record(session, key.id, address="192.0.2.10", user_agent="Zotero")
        await session.refresh(key)
        first = key.last_used

        await keyusage.record(session, key.id, address="192.0.2.10", user_agent="Zotero")

        await session.refresh(key)
        assert key.last_used == first

    async def test_a_different_address_is_written_at_once(self, session: AsyncSession) -> None:
        """The interesting case is exactly the one worth not delaying."""
        await admin.create_user(session, username="ada")
        key = await admin.create_api_key(session, username="ada", name="laptop")
        await keyusage.record(session, key.id, address="192.0.2.10", user_agent="Zotero")

        await keyusage.record(session, key.id, address="198.51.100.7", user_agent="Zotero")

        await session.refresh(key)
        assert key.last_address == "198.51.100.7"

    async def test_the_interval_can_pass(self, session: AsyncSession) -> None:
        await admin.create_user(session, username="ada")
        key = await admin.create_api_key(session, username="ada", name="laptop")
        await keyusage.record(session, key.id, address="192.0.2.10", user_agent="Zotero", now=0.0)
        await session.refresh(key)
        first = key.last_used

        await keyusage.record(
            session,
            key.id,
            address="192.0.2.10",
            user_agent="Zotero",
            now=keyusage.INTERVAL_SECONDS + 1,
        )

        await session.refresh(key)
        assert key.last_used != first

    async def test_an_overlong_user_agent_is_cut_rather_than_refused(
        self, session: AsyncSession
    ) -> None:
        """A header is whatever the caller sent; it must not break a request."""
        await admin.create_user(session, username="ada")
        key = await admin.create_api_key(session, username="ada", name="laptop")

        await keyusage.record(session, key.id, address="192.0.2.10", user_agent="z" * 900)

        await session.refresh(key)
        assert key.last_user_agent is not None
        assert len(key.last_user_agent) <= 255

    async def test_an_unknown_address_is_recorded_as_nothing(self, session: AsyncSession) -> None:
        await admin.create_user(session, username="ada")
        key = await admin.create_api_key(session, username="ada", name="laptop")

        await keyusage.record(session, key.id, address=None, user_agent="Zotero")

        await session.refresh(key)
        assert key.last_used is not None
        assert key.last_address is None

    async def test_a_key_that_has_gone_is_not_an_error(self, session: AsyncSession) -> None:
        """Revoked mid-request is a race, not a failure to report."""
        await keyusage.record(session, 9999, address="192.0.2.10", user_agent="Zotero")


class TestThroughTheApi:
    async def test_using_a_key_records_it(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await admin.create_user(session, username="ada")
        key = await admin.create_api_key(session, username="ada", name="laptop")

        await client.get(
            "/users/1/items",
            headers={"Zotero-API-Key": key.key, "User-Agent": "Zotero/7.0.9"},
        )

        stored = await session.get(ApiKey, key.id)
        assert stored is not None
        await session.refresh(stored)
        assert stored.last_used is not None
        assert stored.last_user_agent == "Zotero/7.0.9"

    async def test_an_unauthenticated_request_records_nothing(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await admin.create_user(session, username="ada")
        key = await admin.create_api_key(session, username="ada", name="laptop")

        await client.get("/users/1/items")

        stored = await session.get(ApiKey, key.id)
        assert stored is not None
        assert stored.last_used is None

    async def test_a_rejected_key_records_nothing(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await admin.create_user(session, username="ada")
        key = await admin.create_api_key(session, username="ada", name="laptop")

        await client.get("/users/1/items", headers={"Zotero-API-Key": "not a real key"})

        stored = await session.get(ApiKey, key.id)
        assert stored is not None
        assert stored.last_used is None

    async def test_a_web_session_does_not_touch_any_key(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The cookie path is not a key, and must not look like one being used."""
        from tests.test_web_routes import register

        await register(client)
        key = await admin.create_api_key(session, username="ada", name="laptop")

        await client.get("/web/libraries")

        stored = await session.get(ApiKey, key.id)
        assert stored is not None
        assert stored.last_used is None
