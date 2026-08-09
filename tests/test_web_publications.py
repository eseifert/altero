"""Publishing an item from the browser, on the desktop client's terms.

The flag itself is `test_publications.py`, against the v3 endpoints. What is
checked here is the conversation around it — which of an item's children go
with it, which licence is written where, and what happens on the way out —
because that is the part the desktop client has and a bare ``inPublications``
does not.

``Zotero.Items.addToPublications`` and ``removeFromPublications``
(``chrome/content/zotero/xpcom/data/items.js``) are the source for every rule
asserted here, and the wizard in ``publicationsDialog.js`` for which
combinations of answers can arrive at all.
"""

import re
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Library
from altero.services import admin
from altero.services.publications import LICENSES
from tests import factories
from tests.test_web_routes import csrf_headers, register

#: The interface's copy of the licence table, which must say the same thing.
LICENSES_TS = (
    Path(__file__).resolve().parent.parent / "web" / "src" / "publications" / "licenses.ts"
)


async def personal_library(client: httpx.AsyncClient) -> int:
    return int((await client.get("/web/libraries")).json()[0]["id"])


@pytest.fixture
async def ada(client: httpx.AsyncClient) -> httpx.AsyncClient:
    """One account, signed in, with its personal library."""
    assert (await register(client)).status_code == 201
    return client


async def api_key(session: AsyncSession, name: str = "seed") -> str:
    key = await admin.create_api_key(session, username="ada", name=name)
    return str(key.key)


async def seed_work(
    client: httpx.AsyncClient,
    session: AsyncSession,
    *,
    rights: str = "",
    with_note: bool = False,
    with_file: bool = False,
    with_link: bool = False,
    with_linked_file: bool = False,
) -> tuple[str, dict[str, str]]:
    """A book and whichever children the test needs, put there by a client.

    Returns:
        The book's key, and the keys of its children by the name this test
        module knows them under.
    """
    headers = {"Zotero-API-Key": await api_key(session)}
    book: dict[str, object] = {"itemType": "book", "title": "The Dispossessed"}
    if rights:
        book["rights"] = rights
    created = await client.post("/users/1/items", headers=headers, json=[book])
    assert created.status_code == 200
    parent = str(created.json()["successful"]["0"]["key"])

    children: list[dict[str, object]] = []
    if with_note:
        children.append({"itemType": "note", "parentItem": parent, "note": "<p>Working notes</p>"})
    if with_file:
        children.append(
            {
                "itemType": "attachment",
                "parentItem": parent,
                "linkMode": "imported_file",
                "title": "Manuscript",
                "filename": "manuscript.pdf",
            }
        )
    if with_link:
        children.append(
            {
                "itemType": "attachment",
                "parentItem": parent,
                "linkMode": "linked_url",
                "title": "Publisher's page",
                "url": "https://example.org/dispossessed",
            }
        )
    if with_linked_file:
        children.append(
            {
                "itemType": "attachment",
                "parentItem": parent,
                "linkMode": "linked_file",
                "title": "On my disk",
                "path": "attachments:dispossessed.pdf",
            }
        )

    keys: dict[str, str] = {}
    if children:
        response = await client.post("/users/1/items", headers=headers, json=children)
        assert response.status_code == 200, response.text
        names = [
            name
            for name, wanted in (
                ("note", with_note),
                ("file", with_file),
                ("link", with_link),
                ("linked_file", with_linked_file),
            )
            if wanted
        ]
        keys = {
            name: str(response.json()["successful"][str(index)]["key"])
            for index, name in enumerate(names)
        }
    return parent, keys


async def publish(
    client: httpx.AsyncClient, library_id: int, key: str, **terms: object
) -> httpx.Response:
    return await client.put(
        f"/web/libraries/{library_id}/publications/items/{key}",
        json=terms,
        headers=csrf_headers(client),
    )


async def unpublish(client: httpx.AsyncClient, library_id: int, key: str) -> httpx.Response:
    return await client.delete(
        f"/web/libraries/{library_id}/publications/items/{key}",
        headers=csrf_headers(client),
    )


async def published(client: httpx.AsyncClient, library_id: int) -> list[str]:
    """The keys the My Publications view of the library holds."""
    payload = (await client.get(f"/web/libraries/{library_id}/items?scope=publications")).json()
    return [entry["key"] for entry in payload["items"]]


async def fetched(client: httpx.AsyncClient, library_id: int, key: str) -> dict[str, object]:
    data: dict[str, object] = (await client.get(f"/web/libraries/{library_id}/items/{key}")).json()[
        "data"
    ]
    return data


class TestPublishingAWork:
    async def test_the_item_is_flagged_and_answered_with(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        book, _ = await seed_work(ada, session)

        response = await publish(ada, library_id, book)

        assert response.status_code == 200
        assert response.json()["data"]["inPublications"] is True
        assert await published(ada, library_id) == [book]

    async def test_one_request_is_one_new_library_version(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """However many items it touches: the work and its children are one act."""
        library_id = await personal_library(ada)
        book, children = await seed_work(ada, session, with_note=True, with_file=True)
        before = int((await ada.get("/web/libraries")).json()[0]["version"])

        response = await publish(ada, library_id, book, includeFiles=True, includeNotes=True)

        version = int(response.headers["Last-Modified-Version"])
        assert version == before + 1
        for key in [book, *children.values()]:
            assert (await fetched(ada, library_id, key))["version"] == version

    async def test_the_children_stay_behind_unless_they_were_asked_for(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        book, children = await seed_work(ada, session, with_note=True, with_file=True)

        await publish(ada, library_id, book)

        assert await published(ada, library_id) == [book]
        assert "inPublications" not in await fetched(ada, library_id, children["note"])
        assert "inPublications" not in await fetched(ada, library_id, children["file"])

    async def test_including_notes_takes_the_notes(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        book, children = await seed_work(ada, session, with_note=True, with_file=True)

        await publish(ada, library_id, book, includeNotes=True)

        assert (await fetched(ada, library_id, children["note"]))["inPublications"] is True
        assert "inPublications" not in await fetched(ada, library_id, children["file"])

    async def test_including_files_takes_the_stored_attachments(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        book, children = await seed_work(ada, session, with_note=True, with_file=True)

        await publish(ada, library_id, book, includeFiles=True)

        assert (await fetched(ada, library_id, children["file"]))["inPublications"] is True
        assert "inPublications" not in await fetched(ada, library_id, children["note"])

    async def test_a_link_attachment_goes_whatever_was_asked(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """``copyOptions.childLinks = true`` on the client's own drop, always.

        A link attachment is a URL rather than a file: publishing it exposes
        nothing the item's own fields do not already say.
        """
        library_id = await personal_library(ada)
        book, children = await seed_work(ada, session, with_link=True)

        await publish(ada, library_id, book)

        assert (await fetched(ada, library_id, children["link"]))["inPublications"] is True

    async def test_a_linked_file_never_goes(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The server does not hold its bytes, so it could not publish them."""
        library_id = await personal_library(ada)
        book, children = await seed_work(ada, session, with_linked_file=True, with_file=True)

        response = await publish(ada, library_id, book, includeFiles=True)

        assert response.status_code == 200
        assert "inPublications" not in await fetched(ada, library_id, children["linked_file"])
        assert (await fetched(ada, library_id, children["file"]))["inPublications"] is True

    async def test_a_child_can_be_published_on_its_own(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The desktop's "Show in My Publications" for a child left behind."""
        library_id = await personal_library(ada)
        book, children = await seed_work(ada, session, with_note=True)
        await publish(ada, library_id, book)

        response = await publish(ada, library_id, children["note"])

        assert response.status_code == 200
        assert (await fetched(ada, library_id, children["note"]))["inPublications"] is True
        # The listing is the top level of the view, as the desktop's is: a
        # published note appears under the work it belongs to, not beside it.
        assert await published(ada, library_id) == [book]


class TestTheLicence:
    async def test_the_chosen_licence_is_written_into_rights(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        book, _ = await seed_work(ada, session)

        await publish(ada, library_id, book, includeFiles=True, license="cc-by")

        assert (await fetched(ada, library_id, book))["rights"] == (
            "Creative Commons Attribution 4.0 International License"
        )

    async def test_keeping_the_rights_field_leaves_what_is_there(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        book, _ = await seed_work(ada, session, rights="© 1974 the author")

        await publish(ada, library_id, book, includeFiles=True, license="cc0", keepRights=True)

        assert (await fetched(ada, library_id, book))["rights"] == "© 1974 the author"

    async def test_not_keeping_it_replaces_what_is_there(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        book, _ = await seed_work(ada, session, rights="© 1974 the author")

        await publish(ada, library_id, book, includeFiles=True, license="cc0", keepRights=False)

        assert (await fetched(ada, library_id, book))["rights"] == (
            "CC0 1.0 Universal Public Domain Dedication"
        )

    async def test_keeping_it_still_fills_an_empty_field(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """``!options.keepRights || !item.getField('rights')`` -- either one."""
        library_id = await personal_library(ada)
        book, _ = await seed_work(ada, session)

        await publish(ada, library_id, book, includeFiles=True, license="cc-by-nc", keepRights=True)

        assert (await fetched(ada, library_id, book))["rights"] == (
            "Creative Commons Attribution-NonCommercial 4.0 International License"
        )

    async def test_no_licence_leaves_the_field_alone(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Publishing without files licenses nothing, and says nothing."""
        library_id = await personal_library(ada)
        book, _ = await seed_work(ada, session, rights="© 1974 the author")

        await publish(ada, library_id, book)

        assert (await fetched(ada, library_id, book))["rights"] == "© 1974 the author"

    async def test_a_licence_nobody_offers_is_refused(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Otherwise the browser writes free text into a published item's rights."""
        library_id = await personal_library(ada)
        book, _ = await seed_work(ada, session)

        response = await publish(
            ada, library_id, book, includeFiles=True, license="do-what-you-like"
        )

        assert response.status_code == 400
        assert "licence" in response.json()["message"]
        assert await published(ada, library_id) == []


class TestTakingItOutAgain:
    async def test_the_item_and_its_children_come_out_together(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        book, _ = await seed_work(ada, session, with_note=True, with_file=True)
        await publish(ada, library_id, book, includeFiles=True, includeNotes=True)

        response = await unpublish(ada, library_id, book)

        assert response.status_code == 200
        assert await published(ada, library_id) == []

    async def test_a_trashed_child_comes_out_too_and_stays_trashed(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """A published note somebody trashed is still published until this."""
        library_id = await personal_library(ada)
        book, children = await seed_work(ada, session, with_note=True)
        await publish(ada, library_id, book, includeNotes=True)
        await ada.patch(
            f"/web/libraries/{library_id}/items",
            json={"items": [children["note"]], "deleted": True},
            headers=csrf_headers(ada),
        )

        await unpublish(ada, library_id, book)

        note = await fetched(ada, library_id, children["note"])
        assert "inPublications" not in note
        assert note["deleted"] == 1

    async def test_the_item_itself_is_untouched_otherwise(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Unpublishing is not deleting: everything else stays where it was."""
        library_id = await personal_library(ada)
        book, children = await seed_work(ada, session, with_note=True)
        await publish(ada, library_id, book, includeNotes=True)

        await unpublish(ada, library_id, book)

        assert (await fetched(ada, library_id, book))["title"] == "The Dispossessed"
        assert (await fetched(ada, library_id, children["note"]))["parentItem"] == book

    async def test_an_item_that_was_never_published_is_refused(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        book, _ = await seed_work(ada, session)

        response = await unpublish(ada, library_id, book)

        assert response.status_code == 400
        assert response.json()["message"] == "Item is not in My Publications"


class TestWhoMayPublish:
    async def test_a_group_library_has_no_my_publications(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        group = await factories.make_group(
            session, group_id=50, owner_id=1, members={}, name="Whale Watchers"
        )
        item = await factories.make_item(session, group, key="AAAA2345")
        await session.commit()

        response = await publish(ada, group.id, item.key)

        assert response.status_code == 400
        assert response.json()["message"] == "Group items cannot be added to My Publications"

    async def test_nobody_publishes_into_someone_elses_library(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """My Publications is one person's, and so is the library behind it."""
        grace = await admin.create_user(session, username="grace")
        theirs = await session.scalar(select(Library).where(Library.owner_id == grace.id))
        assert theirs is not None
        item = await factories.make_item(session, theirs, key="AAAA2345")
        await session.commit()

        response = await publish(ada, theirs.id, item.key)

        assert response.status_code == 403

    async def test_the_csrf_token_is_required(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        book, _ = await seed_work(ada, session)

        response = await ada.put(f"/web/libraries/{library_id}/publications/items/{book}", json={})

        assert response.status_code == 403

    async def test_the_v3_publications_endpoint_still_refuses_writes(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The public listing is to read. Nothing here opened it for writing."""
        key = await api_key(session, name="v3")

        response = await ada.post(
            "/users/1/publications/items", headers={"Zotero-API-Key": key}, json=[]
        )

        assert response.status_code == 403


class TestTheLicenceTable:
    """The server's table and the interface's, which must not drift apart.

    The name is what goes into the ``rights`` field and also what the wizard
    shows before it does; two copies that disagreed would promise one licence
    and store another.
    """

    def test_the_interface_offers_the_same_licences_in_the_same_order(self) -> None:
        source = LICENSES_TS.read_text(encoding="utf-8")
        ids = re.findall(r"id: '([^']+)'", source)

        assert ids == [entry.id for entry in LICENSES]

    def test_the_interface_names_them_the_same_way(self) -> None:
        source = LICENSES_TS.read_text(encoding="utf-8")
        names = re.findall(r"name: '([^']+)'", source)

        assert names == [entry.name for entry in LICENSES]

    def test_the_interface_points_at_the_same_licences(self) -> None:
        source = LICENSES_TS.read_text(encoding="utf-8")
        urls = re.findall(r"url: (?:'([^']+)'|(null))", source)

        assert [found or None for found, _ in urls] == [entry.url for entry in LICENSES]
