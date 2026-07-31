"""The schema endpoints.

The expected shapes in this module were captured from the live API at
https://api.zotero.org so that the vendored schema is exercised against real
responses rather than against assumptions.
"""

import httpx
import pytest

from altero.errors import InvalidInputError
from altero.itemschema import get_schema

# Every item type the live /itemTypes returns, in the order it returns them.
LIVE_ITEM_TYPE_ORDER = [
    "artwork", "audioRecording", "bill", "blogPost", "book", "bookSection", "case",
    "conferencePaper", "dataset", "dictionaryEntry", "document", "email",
    "encyclopediaArticle", "film", "forumPost", "hearing", "instantMessage", "interview",
    "journalArticle", "letter", "magazineArticle", "manuscript", "map", "newspaperArticle",
    "note", "patent", "podcast", "preprint", "presentation", "radioBroadcast", "report",
    "computerProgram", "standard", "statute", "tvBroadcast", "thesis", "videoRecording",
    "webpage",
]  # fmt: skip

# The keys of /items/new?itemType=book, in order.
LIVE_BOOK_TEMPLATE_KEYS = [
    "itemType", "title", "creators", "abstractNote", "series", "seriesNumber", "volume",
    "numberOfVolumes", "edition", "date", "publisher", "place", "originalDate",
    "originalPublisher", "originalPlace", "format", "numPages", "ISBN", "DOI",
    "citationKey", "url", "accessDate", "ISSN", "archive", "archiveLocation", "shortTitle",
    "language", "libraryCatalog", "callNumber", "rights", "extra", "tags", "collections",
    "relations",
]  # fmt: skip


class TestItemTypes:
    async def test_the_order_matches_the_live_api(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/itemTypes")

        assert response.status_code == 200
        assert [entry["itemType"] for entry in response.json()] == LIVE_ITEM_TYPE_ORDER

    async def test_entries_carry_a_localized_name(self, client: httpx.AsyncClient) -> None:
        entries = {
            entry["itemType"]: entry["localized"]
            for entry in (await client.get("/itemTypes")).json()
        }

        assert entries["book"] == "Book"
        assert entries["computerProgram"] == "Software"

    async def test_internal_types_are_hidden(self, client: httpx.AsyncClient) -> None:
        names = {entry["itemType"] for entry in (await client.get("/itemTypes")).json()}

        assert "annotation" not in names
        assert "attachment" not in names
        assert "note" in names

    async def test_a_locale_is_applied(self, client: httpx.AsyncClient) -> None:
        entries = {
            entry["itemType"]: entry["localized"]
            for entry in (await client.get("/itemTypes?locale=de")).json()
        }

        assert entries["book"] == "Buch"

    async def test_a_regional_locale_falls_back_to_its_language(
        self, client: httpx.AsyncClient
    ) -> None:
        entries = {
            entry["itemType"]: entry["localized"]
            for entry in (await client.get("/itemTypes?locale=de-DE")).json()
        }

        assert entries["book"] == "Buch"

    async def test_an_unknown_locale_falls_back_to_english(self, client: httpx.AsyncClient) -> None:
        entries = {
            entry["itemType"]: entry["localized"]
            for entry in (await client.get("/itemTypes?locale=xx-XX")).json()
        }

        assert entries["book"] == "Book"


class TestItemFields:
    async def test_fields_are_ordered_by_localized_name(self, client: httpx.AsyncClient) -> None:
        entries = (await client.get("/itemFields")).json()

        assert [entry["field"] for entry in entries[:4]] == [
            "numPages",
            "numberOfVolumes",
            "abstractNote",
            "accessDate",
        ]

    async def test_base_only_fields_are_excluded(self, client: httpx.AsyncClient) -> None:
        names = {entry["field"] for entry in (await client.get("/itemFields")).json()}

        assert {"title", "publisher", "artworkMedium"} <= names
        # `medium` and `authority` are only ever reached as the base field of
        # another field, and the API does not list them here.
        assert not {"medium", "authority"} & names

    async def test_the_field_count_matches_the_live_api(self, client: httpx.AsyncClient) -> None:
        assert len((await client.get("/itemFields")).json()) == 121


class TestItemTypeFields:
    async def test_fields_are_returned_in_schema_order(self, client: httpx.AsyncClient) -> None:
        entries = (await client.get("/itemTypeFields?itemType=book")).json()

        assert [entry["field"] for entry in entries[:3]] == ["title", "abstractNote", "series"]

    async def test_an_unknown_item_type_is_rejected(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/itemTypeFields?itemType=nosuch")

        assert response.status_code == 400
        assert response.text == "Invalid item type 'nosuch'"

    async def test_a_missing_item_type_is_rejected(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/itemTypeFields")).status_code == 400


class TestItemTypeCreatorTypes:
    async def test_creator_types_match_the_live_api(self, client: httpx.AsyncClient) -> None:
        entries = (await client.get("/itemTypeCreatorTypes?itemType=book")).json()

        assert entries == [
            {"creatorType": "author", "localized": "Author"},
            {"creatorType": "contributor", "localized": "Contributor"},
            {"creatorType": "editor", "localized": "Editor"},
            {"creatorType": "seriesEditor", "localized": "Series Editor"},
            {"creatorType": "translator", "localized": "Translator"},
        ]

    async def test_a_type_without_creators_returns_nothing(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/itemTypeCreatorTypes?itemType=note")).json() == []

    async def test_the_primary_type_leads_and_the_rest_follow_by_localized_name(
        self, client: httpx.AsyncClient
    ) -> None:
        # The schema lists these in a different order, and sorting by the raw
        # name would give a different result again; the live API sorts by the
        # localized name with the primary type pinned in front.
        entries = (await client.get("/itemTypeCreatorTypes?itemType=film&locale=de")).json()

        assert [entry["creatorType"] for entry in entries] == [
            "director",
            "scriptwriter",
            "castMember",
            "narrator",
            "guest",
            "contributor",
            "host",
            "producer",
            "translator",
        ]


class TestCreatorFields:
    async def test_creator_fields_match_the_live_api(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/creatorFields")).json() == [
            {"field": "firstName", "localized": "First"},
            {"field": "lastName", "localized": "Last"},
            {"field": "name", "localized": "Name"},
        ]


class TestTemplates:
    async def test_the_book_template_matches_the_live_api(self, client: httpx.AsyncClient) -> None:
        template = (await client.get("/items/new?itemType=book")).json()

        assert list(template) == LIVE_BOOK_TEMPLATE_KEYS
        assert template["title"] == ""
        assert template["creators"] == [{"creatorType": "author", "firstName": "", "lastName": ""}]
        assert template["tags"] == []
        assert template["collections"] == []
        assert template["relations"] == {}

    async def test_creators_follow_the_types_own_title_field(
        self, client: httpx.AsyncClient
    ) -> None:
        template = (await client.get("/items/new?itemType=case")).json()

        assert list(template)[:3] == ["itemType", "caseName", "creators"]

    @pytest.mark.parametrize("item_type", ["videoRecording", "radioBroadcast"])
    async def test_templates_reproduce_the_upstream_creator_quirk(
        self, client: httpx.AsyncClient, item_type: str
    ) -> None:
        # The schema marks `creator` primary for these types, and
        # /itemTypeCreatorTypes reports it as such, but upstream seeds the
        # template with `director`. Both behaviours are matched deliberately.
        template = (await client.get(f"/items/new?itemType={item_type}")).json()
        creator_types = (await client.get(f"/itemTypeCreatorTypes?itemType={item_type}")).json()

        assert template["creators"][0]["creatorType"] == "director"
        assert creator_types[0]["creatorType"] == "creator"

    async def test_the_note_template_matches_the_live_api(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/items/new?itemType=note")).json() == {
            "itemType": "note",
            "note": "",
            "tags": [],
            "collections": [],
            "relations": {},
        }

    @pytest.mark.parametrize(
        ("link_mode", "expected"),
        [
            (
                "imported_file",
                ["itemType", "linkMode", "title", "accessDate", "note", "tags", "collections",
                 "relations", "contentType", "charset", "filename", "md5", "mtime"],
            ),
            (
                "imported_url",
                ["itemType", "linkMode", "title", "accessDate", "url", "note", "tags",
                 "collections", "relations", "contentType", "charset", "filename", "md5",
                 "mtime"],
            ),
            (
                "linked_file",
                ["itemType", "linkMode", "title", "accessDate", "note", "tags", "collections",
                 "relations", "contentType", "charset", "path"],
            ),
            (
                "linked_url",
                ["itemType", "linkMode", "title", "accessDate", "url", "note", "tags",
                 "collections", "relations", "contentType", "charset"],
            ),
        ],
    )  # fmt: skip
    async def test_attachment_templates_match_the_live_api(
        self, client: httpx.AsyncClient, link_mode: str, expected: list[str]
    ) -> None:
        template = (await client.get(f"/items/new?itemType=attachment&linkMode={link_mode}")).json()

        assert list(template) == expected

    async def test_attachment_null_defaults(self, client: httpx.AsyncClient) -> None:
        template = (
            await client.get("/items/new?itemType=attachment&linkMode=imported_file")
        ).json()

        assert template["md5"] is None
        assert template["mtime"] is None
        assert template["charset"] == ""

    async def test_an_attachment_without_a_link_mode_is_rejected(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.get("/items/new?itemType=attachment")

        assert response.status_code == 400
        assert response.text == "linkMode required for itemType=attachment"

    async def test_an_unknown_link_mode_is_rejected(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/items/new?itemType=attachment&linkMode=nope")

        assert response.status_code == 400

    async def test_an_unknown_item_type_is_rejected(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/items/new?itemType=nosuch")).status_code == 400


class TestFullSchema:
    async def test_the_whole_schema_is_served(self, client: httpx.AsyncClient) -> None:
        body = (await client.get("/schema")).json()

        assert body["version"] == get_schema().version
        assert len(body["itemTypes"]) == 40
        assert "en-US" in body["locales"]


class TestConditionalRequests:
    async def test_responses_carry_a_last_modified_header(self, client: httpx.AsyncClient) -> None:
        assert "Last-Modified" in (await client.get("/itemTypes")).headers

    async def test_an_unchanged_schema_yields_304(self, client: httpx.AsyncClient) -> None:
        last_modified = (await client.get("/itemTypes")).headers["Last-Modified"]

        response = await client.get("/itemTypes", headers={"If-Modified-Since": last_modified})

        assert response.status_code == 304
        assert not response.content

    async def test_an_older_date_still_yields_the_body(self, client: httpx.AsyncClient) -> None:
        response = await client.get(
            "/itemTypes", headers={"If-Modified-Since": "Wed, 01 Jan 2020 00:00:00 GMT"}
        )

        assert response.status_code == 200

    async def test_an_unparseable_date_is_ignored(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/itemTypes", headers={"If-Modified-Since": "nonsense"})

        assert response.status_code == 200


class TestRegistry:
    def test_unknown_item_types_raise_domain_errors(self) -> None:
        with pytest.raises(InvalidInputError, match="Invalid item type"):
            get_schema().get_item_type("nosuch")

    def test_valid_fields_are_exposed_for_write_validation(self) -> None:
        book = get_schema().get_item_type("book")

        assert "title" in book.field_names
        assert "caseName" not in book.field_names
        assert book.primary_creator_type == "author"

    def test_locale_resolution(self) -> None:
        schema = get_schema()

        assert schema.resolve_locale(None) == "en-US"
        assert schema.resolve_locale("de") == "de"
        assert schema.resolve_locale("de-DE") == "de"
        assert schema.resolve_locale("xx") == "en-US"
