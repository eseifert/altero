"""``format=atom``.

The shapes asserted here were read off ``api.zotero.org`` rather than off the
documentation, which describes Atom only in outline. Where altero differs on
purpose -- no ``rel="alternate"``, no ``rel="first"`` on the first page, its own
host in the ``<id>`` -- there is a test saying so, so that a change to any of
them is a decision rather than a slip.

Parsed as XML rather than matched as text: a feed that a reader cannot parse is
the failure that matters, and asserting on strings would not catch it.
"""

from xml.etree import ElementTree

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.atom import ATOM_NAMESPACE, XHTML_NAMESPACE, ZAPI_NAMESPACE
from altero.models import Library
from tests import factories

KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"
HEADERS = {"Zotero-API-Key": KEY}

NS = {"atom": ATOM_NAMESPACE, "zapi": ZAPI_NAMESPACE, "xhtml": XHTML_NAMESPACE}

#: The ``zapi:type`` attribute, as ElementTree spells a namespaced name.
ZAPI_TYPE = f"{{{ZAPI_NAMESPACE}}}type"


def parse(response: httpx.Response) -> ElementTree.Element:
    """Return the document, insisting it is well-formed XML."""
    return ElementTree.fromstring(response.text)


def text(element: ElementTree.Element | None) -> str:
    return "" if element is None else (element.text or "")


@pytest.fixture
async def library(session: AsyncSession) -> Library:
    await factories.make_user(session)
    await factories.make_api_key(session)
    return await factories.make_library(session, owner_id=2, name="Spare")


@pytest.fixture
async def furnished(session: AsyncSession) -> Library:
    from sqlalchemy import select

    from altero.models import LibraryType

    await factories.make_user(session)
    await factories.make_api_key(session)
    library = await session.scalar(
        select(Library).where(Library.type == LibraryType.USER, Library.owner_id == 1)
    )
    assert library is not None

    article = await factories.make_item(
        session,
        library,
        key="AAAA1111",
        item_type="journalArticle",
        fields={
            "title": "On the electrodynamics of moving bodies",
            "date": "1905",
            "publicationTitle": "Annalen der Physik",
        },
        creators=[("author", "Albert", "Einstein")],
    )
    await factories.make_item(
        session,
        library,
        key="BBBB2222",
        item_type="note",
        fields={"note": "<p>A note</p>"},
        parent=article,
    )
    await factories.make_collection(
        session, library, key="CCCC3333", name="Physics", items=[article]
    )
    await factories.make_search(session, library, key="DDDD4444", name="Recent")
    await factories.tag_item(session, library=library, item=article, name="relativity")
    return library


class TestAFeed:
    async def test_it_is_served_as_atom(self, furnished, client: httpx.AsyncClient) -> None:
        response = await client.get("/users/1/items/top?format=atom", headers=HEADERS)

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/atom+xml"

    async def test_it_names_the_library_and_what_it_holds(
        self, furnished, client: httpx.AsyncClient
    ) -> None:
        feed = parse(await client.get("/users/1/items/top?format=atom", headers=HEADERS))

        assert text(feed.find("atom:title", NS)) == "altero / Mona Lisa / Top-Level Items"

    async def test_a_collection_feed_names_the_collection(
        self, furnished, client: httpx.AsyncClient
    ) -> None:
        feed = parse(
            await client.get("/users/1/collections/CCCC3333/items?format=atom", headers=HEADERS)
        )

        assert "Items in Collection" in text(feed.find("atom:title", NS))
        assert "Physics" in text(feed.find("atom:title", NS))

    async def test_it_carries_the_same_headers_a_json_listing_does(
        self, furnished, client: httpx.AsyncClient
    ) -> None:
        """The protocol lives in the headers whatever the body is."""
        response = await client.get("/users/1/items/top?format=atom", headers=HEADERS)

        assert response.headers["Total-Results"] == "1"
        assert response.headers["Last-Modified-Version"] == "0"

    async def test_its_id_is_this_server_rather_than_zotero_org(
        self, furnished, client: httpx.AsyncClient
    ) -> None:
        feed = parse(await client.get("/users/1/items?format=atom", headers=HEADERS))

        assert text(feed.find("atom:id", NS)) == "http://testserver/users/1/items"

    async def test_it_links_to_no_page_on_another_host(
        self, furnished, client: httpx.AsyncClient
    ) -> None:
        """``rel="alternate"`` names zotero.org upstream; altero omits it."""
        feed = parse(await client.get("/users/1/items?format=atom", headers=HEADERS))

        links = feed.findall(".//atom:link", NS)
        assert {link.get("rel") for link in links} == {"self", "up"}
        # The zapi namespace URI legitimately names zotero.org; no *link* may.
        assert not [link for link in links if "zotero.org" in (link.get("href") or "")]

    async def test_it_pages(self, furnished, client: httpx.AsyncClient) -> None:
        feed = parse(await client.get("/users/1/items?format=atom&limit=1", headers=HEADERS))

        rels = {link.get("rel"): link.get("href") for link in feed.findall("atom:link", NS)}
        assert "next" in rels
        assert "start=1" in (rels["next"] or "")

    async def test_an_empty_feed_still_has_an_updated(
        self, library, client: httpx.AsyncClient
    ) -> None:
        """Atom requires it, so a library with nothing in it still carries one."""
        feed = parse(await client.get("/users/1/items?format=atom", headers=HEADERS))

        assert feed.findall("atom:entry", NS) == []
        assert text(feed.find("atom:updated", NS)).endswith("Z")


class TestAnItemEntry:
    async def test_it_reports_the_key_version_and_type(
        self, furnished, client: httpx.AsyncClient
    ) -> None:
        feed = parse(await client.get("/users/1/items/top?format=atom", headers=HEADERS))
        entry = feed.find("atom:entry", NS)
        assert entry is not None

        assert text(entry.find("zapi:key", NS)) == "AAAA1111"
        assert text(entry.find("zapi:itemType", NS)) == "journalArticle"
        assert text(entry.find("zapi:creatorSummary", NS)) == "Einstein"
        assert text(entry.find("zapi:parsedDate", NS)) == "1905"
        assert text(entry.find("zapi:numChildren", NS)) == "1"

    async def test_a_child_item_links_up_and_reports_no_child_count(
        self, furnished, client: httpx.AsyncClient
    ) -> None:
        """Upstream emits ``numChildren`` for a top-level item only."""
        feed = parse(
            await client.get("/users/1/items/AAAA1111/children?format=atom", headers=HEADERS)
        )
        entry = feed.find("atom:entry", NS)
        assert entry is not None

        rels = {link.get("rel") for link in entry.findall("atom:link", NS)}
        assert rels == {"self", "up"}
        assert entry.find("zapi:numChildren", NS) is None

    async def test_a_note_is_titled_by_its_text(self, furnished, client: httpx.AsyncClient) -> None:
        """A note has no title field, so the entry would otherwise be nameless."""
        feed = parse(
            await client.get("/users/1/items/AAAA1111/children?format=atom", headers=HEADERS)
        )
        entry = feed.find("atom:entry", NS)
        assert entry is not None

        assert text(entry.find("atom:title", NS)) == "A note"

    async def test_the_default_body_is_a_table_of_the_item(
        self, furnished, client: httpx.AsyncClient
    ) -> None:
        feed = parse(await client.get("/users/1/items/top?format=atom", headers=HEADERS))
        content = feed.find("atom:entry/atom:content", NS)
        assert content is not None

        assert content.get(ZAPI_TYPE) == "html"
        rows = content.findall(".//xhtml:tr", NS)
        classes = [row.get("class") for row in rows]
        assert classes[:2] == ["itemType", "creator"]
        # The title is the entry's own; upstream leaves it out of the table.
        assert "title" not in classes

    async def test_the_table_uses_the_schema_display_names(
        self, furnished, client: httpx.AsyncClient
    ) -> None:
        feed = parse(await client.get("/users/1/items/top?format=atom", headers=HEADERS))
        cells = feed.findall(".//xhtml:th", NS)

        assert [text(cell) for cell in cells][:2] == ["Item Type", "Author"]

    async def test_content_none_produces_an_empty_body(
        self, furnished, client: httpx.AsyncClient
    ) -> None:
        feed = parse(
            await client.get("/users/1/items/top?format=atom&content=none", headers=HEADERS)
        )
        content = feed.find("atom:entry/atom:content", NS)
        assert content is not None

        assert content.get(ZAPI_TYPE) == "none"
        assert list(content) == []

    async def test_content_json_holds_the_same_object_format_json_serves(
        self, furnished, client: httpx.AsyncClient
    ) -> None:
        """One definition of an item, whichever format asked for it."""
        import json

        feed = parse(
            await client.get("/users/1/items/top?format=atom&content=json", headers=HEADERS)
        )
        content = feed.find("atom:entry/atom:content", NS)
        assert content is not None
        embedded = json.loads(text(content))

        envelope = (await client.get("/users/1/items/top", headers=HEADERS)).json()
        assert embedded == envelope[0]["data"]

    async def test_several_content_values_become_subcontent(
        self, furnished, client: httpx.AsyncClient
    ) -> None:
        feed = parse(
            await client.get("/users/1/items/top?format=atom&content=json,bib", headers=HEADERS)
        )
        content = feed.find("atom:entry/atom:content", NS)
        assert content is not None

        kinds = [part.get(ZAPI_TYPE) for part in content]
        assert kinds == ["bib", "json"]

    async def test_a_bibliography_is_embedded_as_namespaced_xhtml(
        self, furnished, client: httpx.AsyncClient
    ) -> None:
        """Otherwise ``type="xhtml"`` would be a lie and a reader would get
        elements in no namespace at all."""
        feed = parse(
            await client.get("/users/1/items/top?format=atom&content=bib", headers=HEADERS)
        )

        assert feed.find(".//xhtml:div[@class='csl-bib-body']", NS) is not None

    async def test_one_item_answers_with_an_entry_document(
        self, furnished, client: httpx.AsyncClient
    ) -> None:
        entry = parse(await client.get("/users/1/items/AAAA1111?format=atom", headers=HEADERS))

        assert entry.tag == f"{{{ATOM_NAMESPACE}}}entry"
        assert text(entry.find("zapi:key", NS)) == "AAAA1111"


class TestOtherObjects:
    async def test_a_collection_reports_its_counts(
        self, furnished, client: httpx.AsyncClient
    ) -> None:
        feed = parse(await client.get("/users/1/collections?format=atom", headers=HEADERS))
        entry = feed.find("atom:entry", NS)
        assert entry is not None

        assert text(entry.find("zapi:numCollections", NS)) == "0"
        assert text(entry.find("zapi:numItems", NS)) == "1"
        # No rendering of its own, so upstream emits no body at all.
        assert entry.find("atom:content", NS) is None

    async def test_a_saved_search_can_carry_its_json(
        self, furnished, client: httpx.AsyncClient
    ) -> None:
        feed = parse(
            await client.get("/users/1/searches?format=atom&content=json", headers=HEADERS)
        )
        content = feed.find("atom:entry/atom:content", NS)
        assert content is not None

        assert "conditions" in text(content)

    async def test_a_tag_reports_its_item_count(self, furnished, client: httpx.AsyncClient) -> None:
        feed = parse(await client.get("/users/1/tags?format=atom", headers=HEADERS))
        entry = feed.find("atom:entry", NS)
        assert entry is not None

        assert text(entry.find("atom:title", NS)) == "relativity"
        assert text(entry.find("zapi:numItems", NS)) == "1"

    async def test_a_tag_is_dated_by_the_items_carrying_it(
        self, furnished, client: httpx.AsyncClient
    ) -> None:
        """A tag has no timestamp of its own, and Atom insists on one."""
        feed = parse(await client.get("/users/1/tags?format=atom", headers=HEADERS))
        entry = feed.find("atom:entry", NS)
        assert entry is not None

        assert text(entry.find("atom:updated", NS)).endswith("Z")


class TestTheContentParameter:
    async def test_an_unknown_value_is_refused(self, furnished, client: httpx.AsyncClient) -> None:
        response = await client.get("/users/1/items?format=atom&content=nonsense", headers=HEADERS)

        assert response.status_code == 400

    async def test_it_is_refused_outside_atom(self, furnished, client: httpx.AsyncClient) -> None:
        """As ``include`` is refused outside JSON, and for the same reason."""
        response = await client.get("/users/1/items?content=json", headers=HEADERS)

        assert response.status_code == 400

    async def test_a_citation_form_is_refused_on_a_collection(
        self, furnished, client: httpx.AsyncClient
    ) -> None:
        """A collection has no bibliography, so asking for one is an error
        rather than an entry with nothing in it."""
        response = await client.get("/users/1/collections?format=atom&content=bib", headers=HEADERS)

        assert response.status_code == 400

    async def test_none_cannot_be_combined(self, furnished, client: httpx.AsyncClient) -> None:
        response = await client.get("/users/1/items?format=atom&content=none,json", headers=HEADERS)

        assert response.status_code == 400


class TestWhereAtomIsNotOffered:
    async def test_a_write_is_unaffected(self, furnished, client: httpx.AsyncClient) -> None:
        """``format`` describes the response; a POST still answers its report."""
        response = await client.post(
            "/users/1/items?format=atom",
            json=[{"itemType": "book", "title": "Austerlitz"}],
            headers=HEADERS,
        )

        assert response.status_code == 200
        assert response.json()["successful"]

    async def test_the_key_and_version_formats_still_answer_plainly(
        self, furnished, client: httpx.AsyncClient
    ) -> None:
        response = await client.get("/users/1/items?format=keys", headers=HEADERS)

        assert sorted(response.text.splitlines()) == ["AAAA1111", "BBBB2222"]
