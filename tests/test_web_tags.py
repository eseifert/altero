"""Renaming a tag through the browser.

The rename itself is `services/objectwrites.rename_tag`, tested against the v3
endpoint in ``test_objects_write.py``. What is checked here is what only this
door has: a cookie instead of a key, a CSRF token, who may write to which
library, what the panel is answered with, and the version counter moving
exactly once per request — or not at all when nothing changed.
"""

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Item, Library, Tag
from altero.services import admin
from tests import factories
from tests.test_web_routes import csrf_headers, register


async def tag_names(client: httpx.AsyncClient, library_id: int) -> list[str]:
    payload = (await client.get(f"/web/libraries/{library_id}/tags")).json()
    return [entry["tag"] for entry in payload["tags"]]


async def library_version(client: httpx.AsyncClient) -> int:
    return int((await client.get("/web/libraries")).json()[0]["version"])


@pytest.fixture
async def ada(client: httpx.AsyncClient) -> httpx.AsyncClient:
    """One account, signed in, with its personal library."""
    assert (await register(client)).status_code == 201
    return client


@pytest.fixture
async def tagged(session: AsyncSession, ada: httpx.AsyncClient) -> Library:
    """That library, with one item under the tag `ficton`."""
    library = await session.scalar(select(Library).where(Library.owner_id == 1))
    assert library is not None
    item = await factories.make_item(session, library, key="AAAA2345")
    await factories.tag_item(session, library, item, "ficton")
    await session.commit()
    return library


class TestRenamingOne:
    async def test_the_tag_is_renamed(self, ada: httpx.AsyncClient, tagged: Library) -> None:
        response = await ada.patch(
            f"/web/libraries/{tagged.id}/tags/ficton",
            json={"tag": "fiction"},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 200
        assert await tag_names(ada, tagged.id) == ["fiction"]

    async def test_it_comes_back_in_the_shape_the_selector_reads(
        self, ada: httpx.AsyncClient, tagged: Library
    ) -> None:
        body = (
            await ada.patch(
                f"/web/libraries/{tagged.id}/tags/ficton",
                json={"tag": "fiction"},
                headers=csrf_headers(ada),
            )
        ).json()

        assert body == {"tag": "fiction", "type": 0, "numItems": 1, "itemsChanged": 1}

    async def test_the_items_carry_the_new_name(
        self, ada: httpx.AsyncClient, tagged: Library
    ) -> None:
        await ada.patch(
            f"/web/libraries/{tagged.id}/tags/ficton",
            json={"tag": "fiction"},
            headers=csrf_headers(ada),
        )

        body = (await ada.get(f"/web/libraries/{tagged.id}/items/AAAA2345")).json()
        assert body["data"]["tags"] == [{"tag": "fiction"}]

    async def test_a_merge_reports_what_it_left(
        self, ada: httpx.AsyncClient, session: AsyncSession, tagged: Library
    ) -> None:
        """Two tags become one, and the count is the union rather than the sum."""
        item = await session.scalar(select(Item).where(Item.key == "AAAA2345"))
        assert item is not None
        await factories.tag_item(session, tagged, item, "fiction")
        await session.commit()

        body = (
            await ada.patch(
                f"/web/libraries/{tagged.id}/tags/ficton",
                json={"tag": "fiction"},
                headers=csrf_headers(ada),
            )
        ).json()

        assert body == {"tag": "fiction", "type": 0, "numItems": 1, "itemsChanged": 1}
        assert await tag_names(ada, tagged.id) == ["fiction"]

    async def test_the_panel_is_left_with_one_of_the_name_whatever_its_type(
        self, ada: httpx.AsyncClient, session: AsyncSession, tagged: Library
    ) -> None:
        """A name the selector shows twice is a name it filters by once."""
        other = await factories.make_item(session, tagged, key="BBBB2345")
        await factories.tag_item(session, tagged, other, "fiction", tag_type=1)
        await session.commit()

        body = (
            await ada.patch(
                f"/web/libraries/{tagged.id}/tags/ficton",
                json={"tag": "fiction"},
                headers=csrf_headers(ada),
            )
        ).json()

        assert body == {"tag": "fiction", "type": 0, "numItems": 2, "itemsChanged": 2}
        assert await tag_names(ada, tagged.id) == ["fiction"]

    async def test_the_name_is_trimmed(self, ada: httpx.AsyncClient, tagged: Library) -> None:
        await ada.patch(
            f"/web/libraries/{tagged.id}/tags/ficton",
            json={"tag": "  fiction  "},
            headers=csrf_headers(ada),
        )

        assert await tag_names(ada, tagged.id) == ["fiction"]

    async def test_an_empty_name_is_refused(self, ada: httpx.AsyncClient, tagged: Library) -> None:
        response = await ada.patch(
            f"/web/libraries/{tagged.id}/tags/ficton",
            json={"tag": "   "},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 400
        assert await tag_names(ada, tagged.id) == ["ficton"]

    async def test_an_absurd_name_is_refused(self, ada: httpx.AsyncClient, tagged: Library) -> None:
        response = await ada.patch(
            f"/web/libraries/{tagged.id}/tags/ficton",
            json={"tag": "x" * 256},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 400

    async def test_an_unknown_tag_is_not_found(
        self, ada: httpx.AsyncClient, tagged: Library
    ) -> None:
        response = await ada.patch(
            f"/web/libraries/{tagged.id}/tags/novel",
            json={"tag": "fiction"},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 404


class TestTheVersionCounter:
    async def test_one_request_is_one_new_version(
        self, ada: httpx.AsyncClient, session: AsyncSession, tagged: Library
    ) -> None:
        second = await factories.make_item(session, tagged, key="BBBB2345")
        await factories.tag_item(session, tagged, second, "ficton")
        await session.commit()
        before = await library_version(ada)

        await ada.patch(
            f"/web/libraries/{tagged.id}/tags/ficton",
            json={"tag": "fiction"},
            headers=csrf_headers(ada),
        )

        assert await library_version(ada) == before + 1

    async def test_the_answer_carries_the_new_version(
        self, ada: httpx.AsyncClient, tagged: Library
    ) -> None:
        response = await ada.patch(
            f"/web/libraries/{tagged.id}/tags/ficton",
            json={"tag": "fiction"},
            headers=csrf_headers(ada),
        )

        assert int(response.headers["Last-Modified-Version"]) == await library_version(ada)

    async def test_the_name_it_already_has_moves_nothing(
        self, ada: httpx.AsyncClient, tagged: Library
    ) -> None:
        before = await library_version(ada)

        response = await ada.patch(
            f"/web/libraries/{tagged.id}/tags/ficton",
            json={"tag": "ficton"},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 200
        assert response.json()["itemsChanged"] == 0
        assert await library_version(ada) == before

    async def test_a_refused_write_leaves_the_version_alone(
        self, ada: httpx.AsyncClient, tagged: Library
    ) -> None:
        before = await library_version(ada)

        await ada.patch(
            f"/web/libraries/{tagged.id}/tags/ficton",
            json={"tag": ""},
            headers=csrf_headers(ada),
        )

        assert await library_version(ada) == before


class TestWhoMay:
    async def test_it_needs_a_session(self, client: httpx.AsyncClient, tagged: Library) -> None:
        headers = csrf_headers(client)
        client.cookies.delete("altero_session")

        response = await client.patch(
            f"/web/libraries/{tagged.id}/tags/ficton", json={"tag": "fiction"}, headers=headers
        )

        assert response.status_code == 401

    async def test_it_needs_the_csrf_token(self, ada: httpx.AsyncClient, tagged: Library) -> None:
        response = await ada.patch(
            f"/web/libraries/{tagged.id}/tags/ficton", json={"tag": "fiction"}
        )

        assert response.status_code == 403
        assert await tag_names(ada, tagged.id) == ["ficton"]

    async def test_an_api_key_does_not_open_this_door(
        self, ada: httpx.AsyncClient, session: AsyncSession, tagged: Library
    ) -> None:
        """The boundary in both directions: a key belongs to the v3 API."""
        key = await admin.create_api_key(session, username="ada", name="laptop")
        ada.cookies.clear()

        response = await ada.patch(
            f"/web/libraries/{tagged.id}/tags/ficton",
            json={"tag": "fiction"},
            headers={"Zotero-API-Key": key.key, "X-CSRF-Token": "anything"},
        )

        assert response.status_code == 401

    async def test_another_person_s_library_is_refused(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        grace = await admin.create_user(session, username="grace")
        theirs = await session.scalar(select(Library).where(Library.owner_id == grace.id))
        assert theirs is not None
        item = await factories.make_item(session, theirs, key="AAAA2345")
        await factories.tag_item(session, theirs, item, "ficton")
        await session.commit()

        response = await ada.patch(
            f"/web/libraries/{theirs.id}/tags/ficton",
            json={"tag": "fiction"},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 403
        assert await session.scalar(select(Tag.name).where(Tag.library_id == theirs.id)) == "ficton"

    async def test_a_missing_library_is_not_found(self, ada: httpx.AsyncClient) -> None:
        response = await ada.patch(
            "/web/libraries/9999/tags/ficton", json={"tag": "fiction"}, headers=csrf_headers(ada)
        )

        assert response.status_code == 404


class TestGroupPolicy:
    """A group decides who may change its library, and it decides it here too."""

    async def _group(self, session: AsyncSession, editing: str, role: str) -> Library:
        """A group somebody else owns, with Ada in it under ``role``, and a tag."""
        grace = await admin.create_user(session, username="grace")
        library = await factories.make_group(
            session,
            group_id=50,
            owner_id=grace.id,
            members={1: role},
            library_editing=editing,
        )
        item = await factories.make_item(session, library, key="AAAA2345")
        await factories.tag_item(session, library, item, "ficton")
        await session.commit()
        return library

    async def test_a_member_of_an_open_group_may_rename(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library = await self._group(session, editing="members", role="member")

        response = await ada.patch(
            f"/web/libraries/{library.id}/tags/ficton",
            json={"tag": "fiction"},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 200

    async def test_a_member_of_an_admins_only_group_may_not(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library = await self._group(session, editing="admins", role="member")

        response = await ada.patch(
            f"/web/libraries/{library.id}/tags/ficton",
            json={"tag": "fiction"},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 403
        assert await tag_names(ada, library.id) == ["ficton"]

    async def test_an_administrator_of_that_group_may(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library = await self._group(session, editing="admins", role="admin")

        response = await ada.patch(
            f"/web/libraries/{library.id}/tags/ficton",
            json={"tag": "fiction"},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 200
