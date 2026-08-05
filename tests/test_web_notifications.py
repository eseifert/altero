"""Choosing what a group tells you, from the browser.

Same boundary as the rest of ``/web``: cookie only, never an API key, and a
CSRF token on anything that changes something. What is checked here is that the
browser reaches the same preferences the sweep reads, and that a member can
only set their own.
"""

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.settings import Settings


@pytest.fixture
def settings(tmp_path) -> Settings:  # type: ignore[no-untyped-def]
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite'}",
        storage_path=tmp_path / "storage",
    )


async def sign_up(client: httpx.AsyncClient, username: str = "ada") -> httpx.Response:
    return await client.post(
        "/web/auth/register",
        json={
            "username": username,
            "password": "correct horse battery",
            "email": f"{username}@example.org",
        },
    )


def csrf(client: httpx.AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["altero_csrf"]}


@pytest.fixture
async def ada(client: httpx.AsyncClient) -> httpx.AsyncClient:
    assert (await sign_up(client)).status_code == 201
    return client


@pytest.fixture
async def group(ada: httpx.AsyncClient) -> int:
    response = await ada.post("/web/groups", json={"name": "Kollaps"}, headers=csrf(ada))
    assert response.status_code == 201
    return int(response.json()["id"])


class TestReading:
    async def test_a_member_starts_subscribed_to_nothing(
        self, ada: httpx.AsyncClient, group: int
    ) -> None:
        response = await ada.get(f"/web/groups/{group}/notifications")

        assert response.status_code == 200
        assert response.json() == {
            "itemsChanged": False,
            "itemsDeleted": False,
            "membersChanged": False,
            "collectionsChanged": False,
        }

    async def test_the_group_carries_them_too(self, ada: httpx.AsyncClient, group: int) -> None:
        # So the settings panel can render without a second request.
        await ada.put(
            f"/web/groups/{group}/notifications",
            json={"itemsChanged": True},
            headers=csrf(ada),
        )

        response = await ada.get(f"/web/groups/{group}")

        assert response.json()["notifications"]["itemsChanged"] is True

    async def test_a_stranger_cannot_read_them(
        self, client: httpx.AsyncClient, ada: httpx.AsyncClient, group: int
    ) -> None:
        await ada.post("/web/auth/logout", headers=csrf(ada))

        response = await client.get(f"/web/groups/{group}/notifications")

        assert response.status_code in (401, 403)


class TestSetting:
    async def test_one_kind_can_be_turned_on(self, ada: httpx.AsyncClient, group: int) -> None:
        response = await ada.put(
            f"/web/groups/{group}/notifications",
            json={"itemsChanged": True},
            headers=csrf(ada),
        )

        assert response.status_code == 200
        assert response.json()["itemsChanged"] is True
        assert response.json()["itemsDeleted"] is False

    async def test_several_are_set_together(self, ada: httpx.AsyncClient, group: int) -> None:
        response = await ada.put(
            f"/web/groups/{group}/notifications",
            json={"itemsChanged": True, "collectionsChanged": True},
            headers=csrf(ada),
        )

        body = response.json()
        assert (body["itemsChanged"], body["collectionsChanged"]) == (True, True)
        assert (body["itemsDeleted"], body["membersChanged"]) == (False, False)

    async def test_an_omitted_kind_is_left_alone(self, ada: httpx.AsyncClient, group: int) -> None:
        # A partial write, so the panel can send one toggle rather than all of
        # them and two open tabs cannot undo each other's choices.
        await ada.put(
            f"/web/groups/{group}/notifications",
            json={"itemsChanged": True},
            headers=csrf(ada),
        )

        response = await ada.put(
            f"/web/groups/{group}/notifications",
            json={"itemsDeleted": True},
            headers=csrf(ada),
        )

        body = response.json()
        assert (body["itemsChanged"], body["itemsDeleted"]) == (True, True)

    async def test_a_kind_can_be_turned_off(self, ada: httpx.AsyncClient, group: int) -> None:
        await ada.put(
            f"/web/groups/{group}/notifications",
            json={"itemsChanged": True},
            headers=csrf(ada),
        )

        response = await ada.put(
            f"/web/groups/{group}/notifications",
            json={"itemsChanged": False},
            headers=csrf(ada),
        )

        assert response.json()["itemsChanged"] is False

    async def test_setting_them_needs_the_csrf_token(
        self, ada: httpx.AsyncClient, group: int
    ) -> None:
        response = await ada.put(f"/web/groups/{group}/notifications", json={"itemsChanged": True})

        assert response.status_code == 403

    async def test_an_unknown_group_is_not_found(self, ada: httpx.AsyncClient) -> None:
        response = await ada.put(
            "/web/groups/9999/notifications",
            json={"itemsChanged": True},
            headers=csrf(ada),
        )

        assert response.status_code == 404

    async def test_a_non_member_cannot_subscribe(
        self, client: httpx.AsyncClient, ada: httpx.AsyncClient, group: int, session: AsyncSession
    ) -> None:
        # Subscribing is not a way to find out that a private group exists.
        await ada.post("/web/auth/logout", headers=csrf(ada))
        assert (await sign_up(client, "grace")).status_code in (201, 403)

        response = await client.put(
            f"/web/groups/{group}/notifications",
            json={"itemsChanged": True},
            headers=csrf(client),
        )

        assert response.status_code in (401, 403, 404)


class TestTheV3ApiIsUntouched:
    async def test_an_api_key_cannot_set_them(
        self, client: httpx.AsyncClient, ada: httpx.AsyncClient, group: int, session: AsyncSession
    ) -> None:
        # The line the whole interface is built around: a cookie drives /web
        # and an API key drives v3, and neither reaches the other.
        from tests.factories import make_api_key

        await make_api_key(
            session, key="KeyKeyKeyKeyKeyKeyKeyKey", user_id=1, all_groups_write=True
        )

        response = await client.put(
            f"/web/groups/{group}/notifications",
            json={"itemsChanged": True},
            headers={"Zotero-API-Key": "KeyKeyKeyKeyKeyKeyKeyKey"},
        )

        assert response.status_code in (401, 403)
