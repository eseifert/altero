"""CSL JSON, bibliographies and citations."""

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.cite import bibliography, citation, csl_date, csl_item
from altero.models import Item, Library, LibraryType
from altero.services.auth import get_library
from tests.factories import make_api_key, make_item, make_user

KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"
AUTH = {"Zotero-API-Key": KEY}


@pytest.fixture
async def library(session: AsyncSession) -> Library:
    await make_user(session, user_id=1)
    await make_api_key(session, key=KEY, user_id=1)
    library = await get_library(session, LibraryType.USER, 1)
    await session.commit()
    return library


@pytest.fixture
async def article(session: AsyncSession, library: Library) -> Item:
    return await make_item(
        session,
        library,
        key="AAAA2345",
        item_type="journalArticle",
        fields={
            "title": "A study of things",
            "publicationTitle": "Journal of Things",
            "volume": "7",
            "pages": "12-30",
            "date": "2019-04-03",
            "DOI": "10.1000/xyz",
        },
        creators=[("author", "Jane", "Doe")],
    )


class TestCslJson:
    async def test_an_item_maps_onto_csl_variables(
        self, session: AsyncSession, library: Library, article: Item
    ) -> None:
        csl = csl_item(article, library)

        assert csl["id"] == f"{library.id}/AAAA2345"
        assert csl["type"] == "article-journal"
        assert csl["title"] == "A study of things"
        assert csl["container-title"] == "Journal of Things"
        assert csl["page"] == "12-30"
        assert csl["author"] == [{"family": "Doe", "given": "Jane"}]
        assert csl["issued"] == {"date-parts": [[2019, 4, 3]]}

    async def test_a_base_mapped_field_supplies_its_csl_variable(
        self, session: AsyncSession, library: Library
    ) -> None:
        """`container-title` is `publicationTitle`, which a book section calls
        `bookTitle`. Reaching it needs the schema's base-field mapping."""
        section = await make_item(
            session,
            library,
            item_type="bookSection",
            fields={"title": "A chapter", "bookTitle": "The whole book"},
        )

        assert csl_item(section, library)["container-title"] == "The whole book"

    async def test_the_primary_creator_type_becomes_the_author(
        self, session: AsyncSession, library: Library
    ) -> None:
        """An interview's primary creator is the interviewee, and a style asking
        for an author means that person."""
        interview = await make_item(
            session,
            library,
            item_type="interview",
            fields={"title": "A conversation"},
            creators=[("interviewee", "Ada", "Lovelace"), ("interviewer", "Alan", "Turing")],
        )

        csl = csl_item(interview, library)

        assert csl["author"] == [{"family": "Lovelace", "given": "Ada"}]
        assert csl["interviewer"] == [{"family": "Turing", "given": "Alan"}]

    async def test_several_creators_of_one_type_keep_their_order(
        self, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(
            session,
            library,
            creators=[("author", "First", "Alpha"), ("author", "Second", "Beta")],
        )

        assert csl_item(item, library)["author"] == [
            {"family": "Alpha", "given": "First"},
            {"family": "Beta", "given": "Second"},
        ]

    async def test_an_unknown_item_type_is_a_document(
        self, session: AsyncSession, library: Library
    ) -> None:
        note = await make_item(session, library, item_type="note", fields={"note": "<p>Hi</p>"})

        assert csl_item(note, library)["type"] == "document"

    async def test_enclosing_quotes_are_stripped(
        self, session: AsyncSession, library: Library
    ) -> None:
        """Zotero uses quotes around a value to mean "leave this alone", and
        the quotes are not part of the title."""
        item = await make_item(session, library, fields={"title": '"Nineteen Eighty-Four"'})

        assert csl_item(item, library)["title"] == "Nineteen Eighty-Four"


class TestDates:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2019-04-03", {"date-parts": [[2019, 4, 3]]}),
            ("2019-04", {"date-parts": [[2019, 4]]}),
            ("2019", {"date-parts": [[2019]]}),
            ("April 3, 2019", {"date-parts": [[2019, 4, 3]]}),
            ("April 2019", {"date-parts": [[2019, 4]]}),
        ],
    )
    def test_only_the_parts_that_are_present_are_emitted(
        self, raw: str, expected: dict[str, object]
    ) -> None:
        assert csl_date(raw) == expected

    def test_a_season_is_kept_beside_the_year(self) -> None:
        assert csl_date("Spring 2019") == {"date-parts": [[2019]], "season": "Spring"}

    def test_a_date_with_no_year_is_passed_through_literally(self) -> None:
        assert csl_date("forthcoming") == {"literal": "forthcoming"}

    @pytest.mark.parametrize("raw", ["n.d.", "in press", "3 May"])
    def test_a_date_with_no_year_never_borrows_one_from_today(self, raw: str) -> None:
        """A general-purpose date parser fills in what is missing from the
        current date, which turns "no date" into this morning."""
        assert csl_date(raw) == {"literal": raw}

    def test_a_date_in_another_language_is_read(self) -> None:
        assert csl_date("15. März 2020") == {"date-parts": [[2020, 3, 15]]}

    def test_an_empty_date_is_not_a_date(self) -> None:
        assert csl_date("") is None


class TestRendering:
    def _csl(self, **overrides: object) -> dict[str, object]:
        item = {
            "id": "1/AAAA2345",
            "type": "article-journal",
            "title": "A study of things",
            "container-title": "Journal of Things",
            "author": [{"family": "Doe", "given": "Jane"}],
            "issued": {"date-parts": [[2019]]},
            "URL": "https://example.org/study",
        }
        item.update(overrides)
        return item

    def test_a_bibliography_is_wrapped_the_way_the_client_expects(self) -> None:
        html = bibliography([self._csl()], style="apa")

        assert '<div class="csl-bib-body"' in html
        assert 'class="csl-entry"' in html
        assert "Doe" in html

    def test_initials_are_not_followed_by_two_full_stops(self) -> None:
        """The processor and the style each contribute a period. citeproc-js
        drops one; without the same correction every name reads `Doe, J..`."""
        assert ".." not in bibliography([self._csl()], style="apa")

    def test_a_numeric_style_renders_its_citation(self) -> None:
        """IEEE's citation is a group of the citation number and a locator
        macro, which is the shape that goes missing without the corrections in
        `altero.cite.compat`."""
        assert citation(self._csl(), style="ieee") == "<span>[1]</span>"

    def test_an_author_date_style_renders_its_citation(self) -> None:
        assert citation(self._csl(), style="apa") == "<span>(Doe, 2019)</span>"

    def test_a_retired_style_name_still_resolves(self) -> None:
        """`chicago-note-bibliography` is the API's default and was renamed by
        the CSL project years ago. Clients still ask for it."""
        assert bibliography([self._csl()], style="chicago-note-bibliography")

    def test_linkwrap_turns_a_bare_url_into_a_link(self) -> None:
        html = bibliography([self._csl()], style="apa", linkwrap=True)

        assert '<a href="https://example.org/study">https://example.org/study</a>' in html

    def test_urls_are_left_alone_without_linkwrap(self) -> None:
        assert "<a href=" not in bibliography([self._csl()], style="apa")

    def test_an_empty_bibliography_renders_nothing(self) -> None:
        assert bibliography([], style="apa") == ""


class TestFormats:
    async def test_csljson_wraps_the_items(
        self, client: httpx.AsyncClient, library: Library, article: Item
    ) -> None:
        response = await client.get("/users/1/items?format=csljson", headers=AUTH)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith(
            "application/vnd.citationstyles.csl+json"
        )
        assert response.json()["items"][0]["title"] == "A study of things"

    async def test_a_single_item_is_wrapped_the_same_way(
        self, client: httpx.AsyncClient, library: Library, article: Item
    ) -> None:
        """Upstream wraps one item in the same `items` array, with a note in its
        own source saying it would change that in a later API version."""
        response = await client.get("/users/1/items/AAAA2345?format=csljson", headers=AUTH)

        assert response.json()["items"][0]["id"] == f"{library.id}/AAAA2345"

    async def test_bib_renders_html(
        self, client: httpx.AsyncClient, library: Library, article: Item
    ) -> None:
        response = await client.get("/users/1/items?format=bib&style=apa", headers=AUTH)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert '<div class="csl-bib-body"' in response.text
        assert "Doe" in response.text

    async def test_a_bibliography_carries_no_paging_links(
        self, client: httpx.AsyncClient, library: Library, article: Item
    ) -> None:
        response = await client.get("/users/1/items?format=bib", headers=AUTH)

        assert "Link" not in response.headers
        assert response.headers["Total-Results"] == "1"

    async def test_paging_parameters_are_refused_for_a_bibliography(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.get("/users/1/items?format=bib&limit=5", headers=AUTH)

        assert response.status_code == 400
        assert response.text == "'limit' is not valid for format=bib"

    async def test_an_unknown_style_is_reported(
        self, client: httpx.AsyncClient, library: Library, article: Item
    ) -> None:
        response = await client.get("/users/1/items?format=bib&style=not-a-style", headers=AUTH)

        assert response.status_code == 404
        assert response.text == "Style not found"

    async def test_a_style_that_could_not_be_a_name_is_refused(
        self, client: httpx.AsyncClient, library: Library, article: Item
    ) -> None:
        """A URL is a valid style upstream, whose citation server fetches it.
        Fetching one from here would make the server a proxy."""
        response = await client.get(
            "/users/1/items?format=bib&style=https://example.org/evil.csl", headers=AUTH
        )

        assert response.status_code == 400
        assert response.text == "Invalid style"

    async def test_the_citation_formats_are_only_for_items(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.get("/users/1/collections?format=bib", headers=AUTH)

        assert response.status_code == 400
        assert response.text == "Invalid 'format' value 'bib'"

    async def test_keys_is_not_a_format_for_one_object(
        self, client: httpx.AsyncClient, library: Library, article: Item
    ) -> None:
        response = await client.get("/users/1/items/AAAA2345?format=keys", headers=AUTH)

        assert response.status_code == 400


class TestInclude:
    async def test_data_is_included_by_default(
        self, client: httpx.AsyncClient, library: Library, article: Item
    ) -> None:
        (body,) = (await client.get("/users/1/items", headers=AUTH)).json()

        assert "data" in body
        assert "csljson" not in body

    async def test_csljson_can_be_included_beside_the_data(
        self, client: httpx.AsyncClient, library: Library, article: Item
    ) -> None:
        (body,) = (await client.get("/users/1/items?include=data,csljson", headers=AUTH)).json()

        assert body["data"]["title"] == "A study of things"
        assert body["csljson"]["type"] == "article-journal"

    async def test_asking_only_for_a_citation_leaves_the_data_out(
        self, client: httpx.AsyncClient, library: Library, article: Item
    ) -> None:
        (body,) = (await client.get("/users/1/items?include=citation", headers=AUTH)).json()

        assert "data" not in body
        assert body["citation"].startswith("<span>")

    async def test_bib_is_rendered_per_item(
        self, client: httpx.AsyncClient, library: Library, article: Item
    ) -> None:
        (body,) = (await client.get("/users/1/items?include=bib", headers=AUTH)).json()

        assert '<div class="csl-bib-body"' in body["bib"]

    async def test_include_none_leaves_the_envelope_bare(
        self, client: httpx.AsyncClient, library: Library, article: Item
    ) -> None:
        (body,) = (await client.get("/users/1/items?include=none", headers=AUTH)).json()

        assert "data" not in body
        assert body["key"] == "AAAA2345"

    async def test_include_none_cannot_be_combined(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.get("/users/1/items?include=none,data", headers=AUTH)

        assert response.status_code == 400

    async def test_an_unknown_include_value_is_refused(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        """It used to be ignored, which answered 200 with data the client did
        not ask for."""
        response = await client.get("/users/1/items?include=nonsense", headers=AUTH)

        assert response.status_code == 400
        assert response.text == "Invalid 'include' value 'nonsense'"

    async def test_include_is_only_meaningful_for_json(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.get("/users/1/items?format=keys&include=bib", headers=AUTH)

        assert response.status_code == 400
        assert response.text == "'include' is valid only for format=json"

    async def test_a_single_item_honours_include(
        self, client: httpx.AsyncClient, library: Library, article: Item
    ) -> None:
        body = (await client.get("/users/1/items/AAAA2345?include=csljson", headers=AUTH)).json()

        assert body["csljson"]["title"] == "A study of things"
        assert "data" not in body
