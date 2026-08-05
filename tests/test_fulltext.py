"""Full-text content of attachments."""

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Item, Library, LibraryType
from altero.services.auth import get_library
from tests.factories import index_fulltext, make_api_key, make_item, make_user

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


class TestStoringContent:
    async def test_content_round_trips(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="attachment")

        put = await client.put(
            "/users/1/items/AAAA2345/fulltext",
            headers=JSON,
            json={"content": "Call me Ishmael.", "indexedPages": 3, "totalPages": 10},
        )

        assert put.status_code == 204
        body = (await client.get("/users/1/items/AAAA2345/fulltext", headers=AUTH)).json()
        assert body == {
            "content": "Call me Ishmael.",
            "indexedPages": 3,
            "totalPages": 10,
        }

    async def test_statistics_the_client_omits_are_not_invented(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="attachment")

        await client.put(
            "/users/1/items/AAAA2345/fulltext",
            headers=JSON,
            json={"content": "text", "indexedChars": 4, "totalChars": 4},
        )

        body = (await client.get("/users/1/items/AAAA2345/fulltext", headers=AUTH)).json()
        assert set(body) == {"content", "indexedChars", "totalChars"}

    async def test_content_can_be_replaced(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="attachment")

        await client.put(
            "/users/1/items/AAAA2345/fulltext", headers=JSON, json={"content": "first"}
        )
        await client.put(
            "/users/1/items/AAAA2345/fulltext", headers=JSON, json={"content": "second"}
        )

        body = (await client.get("/users/1/items/AAAA2345/fulltext", headers=AUTH)).json()
        assert body["content"] == "second"

    async def test_storing_advances_the_library_version(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="attachment")

        response = await client.put(
            "/users/1/items/AAAA2345/fulltext", headers=JSON, json={"content": "t"}
        )

        assert response.headers["Last-Modified-Version"] == "11"

    async def test_a_body_without_content_is_rejected(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="attachment")

        response = await client.put(
            "/users/1/items/AAAA2345/fulltext", headers=JSON, json={"indexedPages": 1}
        )

        assert response.status_code == 400

    async def test_an_unknown_item_is_a_404(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.put(
            "/users/1/items/ZZZZ2345/fulltext", headers=JSON, json={"content": "t"}
        )

        assert response.status_code == 404

    async def test_writing_requires_write_permission(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await make_user(session, user_id=2, username="reader")
        await make_api_key(session, key="READONLY", user_id=2, library_write=False)
        library = await get_library(session, LibraryType.USER, 2)
        await make_item(session, library, key="AAAA2345", item_type="attachment")

        response = await client.put(
            "/users/2/items/AAAA2345/fulltext",
            headers={"Zotero-API-Key": "READONLY"},
            json={"content": "t"},
        )

        assert response.status_code == 403


class TestReading:
    async def test_an_item_without_content_is_a_404(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="attachment")

        response = await client.get("/users/1/items/AAAA2345/fulltext", headers=AUTH)

        assert response.status_code == 404


class TestVersionIndex:
    async def test_the_index_is_empty_to_begin_with(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        assert (await client.get("/users/1/fulltext", headers=AUTH)).json() == {}

    async def test_the_index_reports_every_indexed_item(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="attachment")
        await make_item(session, library, key="BBBB2345", item_type="attachment")
        await client.put("/users/1/items/AAAA2345/fulltext", headers=JSON, json={"content": "a"})
        await client.put("/users/1/items/BBBB2345/fulltext", headers=JSON, json={"content": "b"})

        body = (await client.get("/users/1/fulltext", headers=AUTH)).json()

        assert body == {"AAAA2345": 11, "BBBB2345": 12}

    async def test_since_filters_the_index(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="attachment")
        await make_item(session, library, key="BBBB2345", item_type="attachment")
        await client.put("/users/1/items/AAAA2345/fulltext", headers=JSON, json={"content": "a"})
        await client.put("/users/1/items/BBBB2345/fulltext", headers=JSON, json={"content": "b"})

        body = (await client.get("/users/1/fulltext?since=11", headers=AUTH)).json()

        assert body == {"BBBB2345": 12}

    async def test_an_unreadable_since_is_rejected(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        assert (await client.get("/users/1/fulltext?since=abc", headers=AUTH)).status_code == 400


class TestBatchUpload:
    """`POST <prefix>/fulltext`, which the desktop client uses to upload.

    The shape comes from `syncFullTextEngine.js` and `syncAPIClient.js`: an
    array of {key, content, indexedChars, totalChars, indexedPages, totalPages},
    answered with the multi-object report. The client reads
    `results[state][index].key` for both `successful` and `unchanged`, so those
    entries are objects rather than bare key strings.
    """

    async def test_a_batch_is_stored(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="attachment")
        await make_item(session, library, key="BBBB2345", item_type="attachment")

        response = await client.post(
            "/users/1/fulltext",
            headers=JSON | {"If-Unmodified-Since-Version": "10"},
            json=[
                {"key": "AAAA2345", "content": "first", "indexedChars": 5, "totalChars": 5},
                {"key": "BBBB2345", "content": "second", "indexedPages": 1, "totalPages": 2},
            ],
        )

        assert response.status_code == 200
        body = response.json()
        assert body["failed"] == {}
        assert body["successful"]["0"]["key"] == "AAAA2345"
        assert body["successful"]["1"]["key"] == "BBBB2345"

    async def test_the_content_is_readable_afterwards(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="attachment")

        await client.post(
            "/users/1/fulltext",
            headers=JSON | {"If-Unmodified-Since-Version": "10"},
            json=[{"key": "AAAA2345", "content": "Call me Ishmael.", "indexedChars": 16}],
        )

        body = (await client.get("/users/1/items/AAAA2345/fulltext", headers=AUTH)).json()
        assert body["content"] == "Call me Ishmael."
        assert body["indexedChars"] == 16

    async def test_successful_entries_carry_a_key(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # The client does results[state][index].key; a bare string would leave
        # it looking up an item by undefined.
        await make_item(session, library, key="AAAA2345", item_type="attachment")

        body = (
            await client.post(
                "/users/1/fulltext",
                headers=JSON | {"If-Unmodified-Since-Version": "10"},
                json=[{"key": "AAAA2345", "content": "t"}],
            )
        ).json()

        assert set(body) == {"successful", "success", "unchanged", "failed"}
        assert "key" in body["successful"]["0"]

    async def test_an_unknown_item_fails_that_entry_only(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="attachment")

        body = (
            await client.post(
                "/users/1/fulltext",
                headers=JSON | {"If-Unmodified-Since-Version": "10"},
                json=[
                    {"key": "AAAA2345", "content": "fine"},
                    {"key": "ZZZZ2345", "content": "no such item"},
                ],
            )
        ).json()

        assert set(body["successful"]) == {"0"}
        assert body["failed"]["1"]["code"] == 404
        assert body["failed"]["1"]["key"] == "ZZZZ2345"

    async def test_an_entry_without_a_key_fails(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        body = (
            await client.post(
                "/users/1/fulltext",
                headers=JSON | {"If-Unmodified-Since-Version": "10"},
                json=[{"content": "orphan"}],
            )
        ).json()

        assert body["failed"]["0"]["code"] == 400
        assert "key" in body["failed"]["0"]["message"].lower()

    async def test_the_version_advances_once_for_the_whole_batch(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="attachment")
        await make_item(session, library, key="BBBB2345", item_type="attachment")

        response = await client.post(
            "/users/1/fulltext",
            headers=JSON | {"If-Unmodified-Since-Version": "10"},
            json=[
                {"key": "AAAA2345", "content": "a"},
                {"key": "BBBB2345", "content": "b"},
            ],
        )

        assert response.headers["Last-Modified-Version"] == "11"

    async def test_a_missing_version_header_is_refused(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="attachment")

        response = await client.post(
            "/users/1/fulltext", headers=JSON, json=[{"key": "AAAA2345", "content": "t"}]
        )

        assert response.status_code == 428

    async def test_a_stale_version_header_is_refused(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # The client expects 412 here and retries the whole sync.
        await make_item(session, library, key="AAAA2345", item_type="attachment")

        response = await client.post(
            "/users/1/fulltext",
            headers=JSON | {"If-Unmodified-Since-Version": "3"},
            json=[{"key": "AAAA2345", "content": "t"}],
        )

        assert response.status_code == 412

    async def test_uploading_requires_write_permission(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await make_user(session, user_id=2, username="reader")
        await make_api_key(session, key="READONLY", user_id=2, library_write=False)

        response = await client.post(
            "/users/2/fulltext",
            headers={"Zotero-API-Key": "READONLY", "If-Unmodified-Since-Version": "0"},
            json=[],
        )

        assert response.status_code == 403


class TestSearching:
    """`q` with `qmode=everything` reaching an attachment's stored text.

    Upstream runs the search against Elasticsearch and ORs the item keys it
    returns into the same clause as the title, creator and year match --
    `Zotero_FullText::searchInLibrary`, called from `Zotero_Items::search`.
    altero has no index to ask, so it matches the stored text directly; what
    the two have in common is where the result is joined in, which is what
    decides the answers below.
    """

    @pytest.fixture
    async def article(self, session: AsyncSession, library: Library) -> Item:
        """An article whose PDF mentions something its metadata does not."""
        parent = await make_item(session, library, key="PARENT234", fields={"title": "On Whaling"})
        pdf = await make_item(
            session, library, key="CHILD2345", item_type="attachment", parent=parent
        )
        await index_fulltext(session, library, pdf, "Call me Ishmael. The Pequod sailed.")
        return parent

    async def test_stored_text_is_searched(self, client: httpx.AsyncClient, article: Item) -> None:
        response = await client.get("/users/1/items?q=Pequod&qmode=everything", headers=AUTH)

        assert [item["key"] for item in response.json()] == ["CHILD2345"]

    async def test_the_default_mode_does_not_search_it(
        self, client: httpx.AsyncClient, article: Item
    ) -> None:
        # titleCreatorYear is the item's own metadata and nothing else, so a
        # word that appears only in the PDF must not match.
        response = await client.get("/users/1/items?q=Pequod", headers=AUTH)

        assert response.json() == []

    async def test_a_match_in_top_mode_answers_with_the_parent(
        self, client: httpx.AsyncClient, article: Item
    ) -> None:
        # The attachment is never top-level, so the hit is only useful if it
        # surfaces the item it hangs under -- which is the scope the web
        # interface and the web library list items in.
        response = await client.get("/users/1/items/top?q=Pequod&qmode=everything", headers=AUTH)

        assert [item["key"] for item in response.json()] == ["PARENT234"]

    async def test_the_parent_is_answered_once_however_many_children_match(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library, article: Item
    ) -> None:
        second = await make_item(
            session, library, key="CHILD3456", item_type="attachment", parent=article
        )
        await index_fulltext(session, library, second, "The Pequod again.")

        response = await client.get("/users/1/items/top?q=Pequod&qmode=everything", headers=AUTH)

        assert [item["key"] for item in response.json()] == ["PARENT234"]

    async def test_text_in_another_library_is_not_reached(
        self, client: httpx.AsyncClient, session: AsyncSession, article: Item
    ) -> None:
        await make_user(session, user_id=2, username="other")
        elsewhere = await get_library(session, LibraryType.USER, 2)
        stranger = await make_item(session, elsewhere, key="OTHER2345", item_type="attachment")
        await index_fulltext(session, elsewhere, stranger, "The Pequod sailed.")

        response = await client.get("/users/1/items?q=Pequod&qmode=everything", headers=AUTH)

        assert [item["key"] for item in response.json()] == ["CHILD2345"]

    async def test_a_trashed_parent_is_not_surfaced(
        self, client: httpx.AsyncClient, session: AsyncSession, article: Item
    ) -> None:
        # Upstream joins deletedItems a second time on the top-level item for
        # exactly this, so a hit inside a trashed item's PDF stays out of the
        # listing rather than resurrecting it.
        article.deleted = True
        await session.commit()

        response = await client.get("/users/1/items/top?q=Pequod&qmode=everything", headers=AUTH)

        assert response.json() == []

    async def test_an_annotation_surfaces_its_grandparent(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library, article: Item
    ) -> None:
        # item -> attachment -> annotation is as deep as Zotero goes, and /top
        # has to climb all of it.
        pdf = await make_item(
            session, library, key="CHILD4567", item_type="attachment", parent=article
        )
        await make_item(
            session,
            library,
            key="NOTE45678",
            item_type="annotation",
            parent=pdf,
            fields={"annotationText": "harpoon"},
        )

        response = await client.get("/users/1/items/top?q=harpoon&qmode=everything", headers=AUTH)

        assert [item["key"] for item in response.json()] == ["PARENT234"]

    async def test_every_word_of_a_query_must_match(
        self, client: httpx.AsyncClient, article: Item
    ) -> None:
        # Upstream emits one `AND (...)` per part, so both words are required.
        both = await client.get("/users/1/items?q=Ishmael Pequod&qmode=everything", headers=AUTH)
        missing = await client.get(
            "/users/1/items?q=Ishmael Nantucket&qmode=everything", headers=AUTH
        )

        assert [item["key"] for item in both.json()] == ["CHILD2345"]
        assert missing.json() == []

    async def test_words_do_not_combine_across_a_parent_and_its_child(
        self, client: httpx.AsyncClient, article: Item
    ) -> None:
        # Every part is applied to the same row, so a word from the parent's
        # title and a word from the child's text do not add up to a match, even
        # though /top would have answered with that parent for either alone.
        # The clauses are per-item; only the last step climbs to the parent.
        together = await client.get(
            "/users/1/items/top?q=Whaling Pequod&qmode=everything", headers=AUTH
        )
        title_alone = await client.get(
            "/users/1/items/top?q=Whaling&qmode=everything", headers=AUTH
        )

        assert together.json() == []
        assert [item["key"] for item in title_alone.json()] == ["PARENT234"]

    async def test_a_quoted_phrase_stays_one_part(
        self, client: httpx.AsyncClient, article: Item
    ) -> None:
        # Quoted, the words have to be adjacent; unquoted they need not be.
        phrase = await client.get('/users/1/items?q="me Ishmael"&qmode=everything', headers=AUTH)
        reversed_phrase = await client.get(
            '/users/1/items?q="Ishmael me"&qmode=everything', headers=AUTH
        )

        assert [item["key"] for item in phrase.json()] == ["CHILD2345"]
        assert reversed_phrase.json() == []

    async def test_case_is_ignored_but_accents_are_not(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # Upstream's index carries no `asciifolding` filter, so its search is
        # accent-sensitive too and `cafe` does not reach `café`. The Zotero 9
        # client folds accents when it searches its own copy, which the server
        # has never done -- against api.zotero.org just as much as here.
        item = await make_item(session, library, key="ACCENT234", item_type="attachment")
        await index_fulltext(session, library, item, "Le café était fermé.")

        async def search(term: str) -> list[str]:
            response = await client.get(f"/users/1/items?q={term}&qmode=everything", headers=AUTH)
            return [found["key"] for found in response.json()]

        assert await search("CAFÉ") == ["ACCENT234"]
        assert await search("cafe") == []

    async def test_cjk_text_matches_as_a_phrase(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # Matching characters rather than words means adjacency is required,
        # which is what a reader of Chinese or Japanese wants and what the
        # client's own search had to be fixed to do in Zotero 9. Nothing here
        # had to be built for it -- it falls out of matching substrings.
        item = await make_item(session, library, key="KANJI2345", item_type="attachment")
        await index_fulltext(session, library, item, "量子計算の研究について")

        async def search(term: str) -> list[str]:
            response = await client.get(f"/users/1/items?q={term}&qmode=everything", headers=AUTH)
            return [found["key"] for found in response.json()]

        assert await search("量子計算") == ["KANJI2345"]
        assert await search("計算量子") == []
