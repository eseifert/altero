"""Library settings."""

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Library, LibraryType
from altero.services.auth import get_library
from tests.factories import make_api_key, make_user

KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"
AUTH = {"Zotero-API-Key": KEY}
JSON = AUTH | {"Content-Type": "application/json"}
VERSIONED = AUTH | {"If-Unmodified-Since-Version": "10"}

TAG_COLORS = [{"name": "urgent", "color": "#FF6666"}]


@pytest.fixture
async def library(session: AsyncSession) -> Library:
    await make_user(session, user_id=1)
    await make_api_key(session, key=KEY, user_id=1)
    library = await get_library(session, LibraryType.USER, 1)
    library.version = 10
    await session.commit()
    return library


class TestReading:
    async def test_an_empty_library_has_no_settings(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        response = await client.get("/users/1/settings", headers=AUTH)

        assert response.status_code == 200
        assert response.json() == {}
        assert response.headers["Last-Modified-Version"] == "10"

    async def test_settings_are_keyed_by_name(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        await client.post(
            "/users/1/settings", headers=JSON, json={"tagColors": {"value": TAG_COLORS}}
        )

        body = (await client.get("/users/1/settings", headers=AUTH)).json()

        assert list(body) == ["tagColors"]
        assert body["tagColors"]["value"] == TAG_COLORS
        assert body["tagColors"]["version"] == 11

    async def test_one_setting_is_returned_alone(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        await client.put("/users/1/settings/tagColors", headers=JSON, json={"value": TAG_COLORS})

        body = (await client.get("/users/1/settings/tagColors", headers=AUTH)).json()

        assert body == {"value": TAG_COLORS, "version": 11}

    async def test_an_unknown_setting_is_a_404(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        response = await client.get("/users/1/settings/nope", headers=AUTH)

        assert response.status_code == 404
        assert response.text == "Setting not found"

    async def test_since_filters_settings(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        await client.put("/users/1/settings/old", headers=JSON, json={"value": 1})
        await client.put("/users/1/settings/new", headers=JSON, json={"value": 2})

        body = (await client.get("/users/1/settings?since=11", headers=AUTH)).json()

        assert list(body) == ["new"]

    async def test_reading_requires_authorisation(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        assert (await client.get("/users/1/settings")).status_code == 403


class TestWriting:
    async def test_a_setting_is_stored(self, client: httpx2.AsyncClient, library: Library) -> None:
        response = await client.put(
            "/users/1/settings/tagColors", headers=JSON, json={"value": TAG_COLORS}
        )

        assert response.status_code == 204
        assert response.headers["Last-Modified-Version"] == "11"

    async def test_any_json_value_is_accepted(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        # The server never interprets what a setting means.
        for value in (1, "text", True, None, [1, 2], {"nested": {"deep": True}}):
            response = await client.put(
                "/users/1/settings/thing", headers=JSON, json={"value": value}
            )
            assert response.status_code == 204

            body = (await client.get("/users/1/settings/thing", headers=AUTH)).json()
            assert body["value"] == value

    async def test_a_batch_is_stored_at_one_version(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        response = await client.post(
            "/users/1/settings",
            headers=JSON,
            json={"tagColors": {"value": TAG_COLORS}, "feeds": {"value": {}}},
        )

        assert response.status_code == 204
        body = (await client.get("/users/1/settings", headers=AUTH)).json()
        assert {s["version"] for s in body.values()} == {11}

    async def test_a_body_without_a_value_is_rejected(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        response = await client.put("/users/1/settings/tagColors", headers=JSON, json={"nope": 1})

        assert response.status_code == 400

    async def test_a_stale_version_is_rejected(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        await client.put("/users/1/settings/thing", headers=JSON, json={"value": 1})

        response = await client.put(
            "/users/1/settings/thing", headers=JSON, json={"value": 2, "version": 3}
        )

        assert response.status_code == 412

    async def test_writing_requires_write_permission(
        self, client: httpx2.AsyncClient, session: AsyncSession
    ) -> None:
        await make_user(session, user_id=2, username="reader")
        await make_api_key(session, key="READONLY", user_id=2, library_write=False)

        response = await client.put(
            "/users/2/settings/thing",
            headers={"Zotero-API-Key": "READONLY"},
            json={"value": 1},
        )

        assert response.status_code == 403


class TestUnchanged:
    """A setting written as it is stored changes nothing, as upstream.

    `Zotero_Setting::__set` marks a setting changed only when the value
    differs, `save` writes nothing for one that did not, and the controller
    rolls back and answers the library's original version when nothing in the
    request changed. Moving the version anyway sends every other client and
    stream subscriber into a sync for nothing.
    """

    async def test_a_batch_that_changes_nothing_keeps_the_version(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        body = {"tagColors": {"value": TAG_COLORS}, "feeds": {"value": {}}}
        await client.post("/users/1/settings", headers=JSON, json=body)

        response = await client.post("/users/1/settings", headers=JSON, json=body)

        assert response.status_code == 204
        assert response.headers["Last-Modified-Version"] == "11"
        listed = await client.get("/users/1/settings", headers=AUTH)
        assert listed.headers["Last-Modified-Version"] == "11"

    async def test_only_what_changed_takes_the_new_version(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        await client.post(
            "/users/1/settings",
            headers=JSON,
            json={"tagColors": {"value": TAG_COLORS}, "feeds": {"value": {}}},
        )

        response = await client.post(
            "/users/1/settings",
            headers=JSON,
            json={"tagColors": {"value": TAG_COLORS}, "feeds": {"value": {"a": 1}}},
        )

        assert response.headers["Last-Modified-Version"] == "12"
        body = (await client.get("/users/1/settings", headers=AUTH)).json()
        assert (body["tagColors"]["version"], body["feeds"]["version"]) == (11, 12)

    async def test_putting_the_same_value_keeps_the_version(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        await client.put(
            "/users/1/settings/lastPageIndex_u_ABCD2345", headers=JSON, json={"value": 3}
        )

        response = await client.put(
            "/users/1/settings/lastPageIndex_u_ABCD2345", headers=JSON, json={"value": 3}
        )

        assert response.status_code == 204
        assert response.headers["Last-Modified-Version"] == "11"

    async def test_a_number_of_another_type_is_a_change(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        """Upstream compares scalars with `!==`, so 3 and 3.0 differ."""
        await client.put(
            "/users/1/settings/lastPageIndex_u_ABCD2345", headers=JSON, json={"value": 3}
        )

        response = await client.put(
            "/users/1/settings/lastPageIndex_u_ABCD2345", headers=JSON, json={"value": 3.0}
        )

        assert response.headers["Last-Modified-Version"] == "12"


class TestDeleting:
    @pytest.mark.parametrize("method", ["PUT", "POST"])
    async def test_recreated_setting_leaves_the_delete_log(self, client, library, method):
        await client.put("/users/1/settings/tagColors", headers=JSON, json={"value": TAG_COLORS})
        deleted = await client.delete(
            "/users/1/settings/tagColors", headers=AUTH | {"If-Unmodified-Since-Version": "11"}
        )
        assert deleted.status_code == 204
        if method == "PUT":
            recreated = await client.put(
                "/users/1/settings/tagColors", headers=JSON, json={"value": TAG_COLORS}
            )
        else:
            recreated = await client.post(
                "/users/1/settings", headers=JSON, json={"tagColors": {"value": TAG_COLORS}}
            )
        assert recreated.status_code == 204
        log = (await client.get("/users/1/deleted?since=11", headers=AUTH)).json()
        assert log["settings"] == [], "A stale deletion would remove the recreated desktop setting"

    async def test_a_setting_is_deleted(self, client: httpx2.AsyncClient, library: Library) -> None:
        await client.put("/users/1/settings/thing", headers=JSON, json={"value": 1})

        response = await client.delete(
            "/users/1/settings/thing", headers=AUTH | {"If-Unmodified-Since-Version": "11"}
        )

        assert response.status_code == 204
        assert (await client.get("/users/1/settings/thing", headers=AUTH)).status_code == 404

    async def test_deleting_without_a_version_is_rejected(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        await client.put("/users/1/settings/thing", headers=JSON, json={"value": 1})

        assert (await client.delete("/users/1/settings/thing", headers=AUTH)).status_code == 428

    async def test_several_settings_are_deleted_by_key(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        await client.post(
            "/users/1/settings", headers=JSON, json={"a": {"value": 1}, "b": {"value": 2}}
        )

        response = await client.delete(
            "/users/1/settings?settingKey=a,b",
            headers=AUTH | {"If-Unmodified-Since-Version": "11"},
        )

        assert response.status_code == 204
        assert (await client.get("/users/1/settings", headers=AUTH)).json() == {}

    async def test_deleting_without_a_key_is_rejected(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        response = await client.delete("/users/1/settings", headers=VERSIONED)

        assert response.status_code == 400
        assert response.text == "settingKey parameter not provided"

    async def test_a_deleted_setting_reaches_the_delete_log(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        # The delete log has always had a settings group; until now nothing
        # could put anything in it.
        await client.put("/users/1/settings/thing", headers=JSON, json={"value": 1})
        await client.delete(
            "/users/1/settings/thing", headers=AUTH | {"If-Unmodified-Since-Version": "11"}
        )

        body = (await client.get("/users/1/deleted?since=10", headers=AUTH)).json()

        assert body["settings"] == ["thing"]
