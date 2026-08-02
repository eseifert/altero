"""``inPublications``, the My Publications flag on an item.

Upstream accepts it as an ordinary item property, with three refusals attached
(``Zotero_Items::validateJSONItem``): a group library has no My Publications, a
top-level note or attachment cannot be in it, and neither can a linked-file
attachment, whose bytes the server does not hold. It is emitted only when true,
the way ``deleted`` is.

altero rejected the property outright with "Invalid field", which is a per-item
400 for anything a user had put in My Publications -- and a client that cannot
upload an item does not give up, it keeps sending it.
"""

from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Library, LibraryType
from altero.services.auth import get_library
from tests.factories import make_api_key, make_group, make_user

KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"
AUTH = {"Zotero-API-Key": KEY}
JSON = AUTH | {"Content-Type": "application/json"}


@pytest.fixture
async def library(session: AsyncSession) -> Library:
    await make_user(session, user_id=1)
    await make_api_key(session, key=KEY, user_id=1)
    library = await get_library(session, LibraryType.USER, 1)
    library.version = 10
    await session.commit()
    return library


@pytest.fixture
async def group(session: AsyncSession) -> Library:
    """A group library, with a key allowed to write to it."""
    await make_user(session, user_id=1)
    await make_api_key(session, key=KEY, user_id=1, all_groups_read=True, all_groups_write=True)
    return await make_group(session, group_id=2, owner_id=1, name="Research")


async def post(
    client: httpx.AsyncClient, path: str, payload: list[dict[str, Any]]
) -> httpx.Response:
    return await client.post(path, headers=JSON, json=payload)


class TestAcceptingTheProperty:
    async def test_an_item_can_be_put_in_my_publications(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await post(
            client,
            "/users/1/items",
            [{"itemType": "book", "title": "Dune", "inPublications": True}],
        )

        assert response.status_code == 200
        assert response.json()["failed"] == {}
        assert response.json()["successful"]["0"]["data"]["inPublications"] is True

    async def test_it_survives_a_round_trip_through_the_api(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        created = await post(
            client,
            "/users/1/items",
            [{"itemType": "book", "title": "Dune", "inPublications": True}],
        )
        key = created.json()["successful"]["0"]["data"]["key"]

        fetched = await client.get(f"/users/1/items/{key}", headers=AUTH)

        assert fetched.json()["data"]["inPublications"] is True

    async def test_it_is_omitted_rather_than_false(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        # Upstream emits the key only when true, as it does for `deleted`.
        # Emitting `false` would put a property on every item in every library.
        created = await post(client, "/users/1/items", [{"itemType": "book", "title": "Dune"}])

        assert "inPublications" not in created.json()["successful"]["0"]["data"]

    async def test_a_falsy_value_is_accepted_and_stored_as_absent(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        created = await post(
            client,
            "/users/1/items",
            [{"itemType": "book", "title": "Dune", "inPublications": False}],
        )

        assert created.json()["failed"] == {}
        assert "inPublications" not in created.json()["successful"]["0"]["data"]

    async def test_a_replacing_write_clears_it(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        # A full write with the property absent means false, as for any other
        # property a replacing write does not mention.
        created = await post(
            client,
            "/users/1/items",
            [{"itemType": "book", "title": "Dune", "inPublications": True}],
        )
        stored = created.json()["successful"]["0"]["data"]
        del stored["inPublications"]

        again = await post(client, "/users/1/items", [stored])

        assert "inPublications" not in again.json()["successful"]["0"]["data"]

    async def test_a_child_attachment_may_be_in_publications(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        # Only *top-level* notes and attachments are refused; a child of a
        # published item is exactly what My Publications is for.
        parent = await post(client, "/users/1/items", [{"itemType": "book", "title": "Dune"}])
        parent_key = parent.json()["successful"]["0"]["data"]["key"]

        response = await post(
            client,
            "/users/1/items",
            [
                {
                    "itemType": "attachment",
                    "parentItem": parent_key,
                    "linkMode": "imported_url",
                    "title": "Snapshot",
                    "inPublications": True,
                }
            ],
        )

        assert response.json()["failed"] == {}


class TestRefusals:
    async def test_a_group_item_cannot_be_in_my_publications(
        self, client: httpx.AsyncClient, group: Library
    ) -> None:
        response = await post(
            client,
            "/groups/2/items",
            [{"itemType": "book", "title": "Dune", "inPublications": True}],
        )

        failure = response.json()["failed"]["0"]
        assert failure["code"] == 400
        assert failure["message"] == "Group items cannot be added to My Publications"

    async def test_a_group_item_may_still_carry_a_falsy_value(
        self, client: httpx.AsyncClient, group: Library
    ) -> None:
        # Upstream stops checking the moment the value is falsy, so a client
        # sending inPublications:false to a group is not an error.
        response = await post(
            client,
            "/groups/2/items",
            [{"itemType": "book", "title": "Dune", "inPublications": False}],
        )

        assert response.json()["failed"] == {}

    @pytest.mark.parametrize("item_type", ["note", "attachment"])
    async def test_a_top_level_note_or_attachment_is_refused(
        self, client: httpx.AsyncClient, library: Library, item_type: str
    ) -> None:
        payload: dict[str, Any] = {"itemType": item_type, "inPublications": True}
        if item_type == "attachment":
            payload["linkMode"] = "imported_url"

        response = await post(client, "/users/1/items", [payload])

        failure = response.json()["failed"]["0"]
        assert failure["code"] == 400
        assert (
            failure["message"]
            == "Top-level notes and attachments cannot be added to My Publications"
        )

    async def test_a_linked_file_attachment_is_refused(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        # The server does not hold the bytes of a linked file, so it could not
        # publish them.
        parent = await post(client, "/users/1/items", [{"itemType": "book", "title": "Dune"}])
        parent_key = parent.json()["successful"]["0"]["data"]["key"]

        response = await post(
            client,
            "/users/1/items",
            [
                {
                    "itemType": "attachment",
                    "parentItem": parent_key,
                    "linkMode": "linked_file",
                    "title": "On disk",
                    "inPublications": True,
                }
            ],
        )

        failure = response.json()["failed"]["0"]
        assert failure["code"] == 400
        assert failure["message"] == "Linked-file attachments cannot be added to My Publications"


class TestInteractionWithTheRest:
    async def test_toggling_it_is_not_an_unchanged_write(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        # A property left out of the unchanged comparison would let a change to
        # it disappear, reported as unchanged and never stored.
        created = await post(client, "/users/1/items", [{"itemType": "book", "title": "Dune"}])
        stored = created.json()["successful"]["0"]["data"]

        again = await post(client, "/users/1/items", [{**stored, "inPublications": True}])

        assert again.json()["unchanged"] == {}
        assert again.json()["successful"]["0"]["data"]["inPublications"] is True

    async def test_an_item_in_publications_resent_verbatim_is_unchanged(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        created = await post(
            client,
            "/users/1/items",
            [{"itemType": "book", "title": "Dune", "inPublications": True}],
        )
        stored = created.json()["successful"]["0"]["data"]

        again = await post(client, "/users/1/items", [stored])

        assert again.json()["unchanged"] == {"0": stored["key"]}
