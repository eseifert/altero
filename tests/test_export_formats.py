"""The export formats that are ports of Zotero's own translators.

Every expected string here was taken from `api.zotero.org` for a real item and
then reproduced from the same item's fields, so a change that looks harmless and
moves a byte fails. Where altero deliberately writes something else, the test
says so and says why.
"""

import csv
import io

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.cite import exportitem
from altero.cite import formats as exportformats
from altero.models import Item, Library, LibraryType
from altero.query import EXPORT_FORMATS, Format
from altero.services.auth import get_library
from tests.factories import make_api_key, make_item, make_user

KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"
AUTH = {"Zotero-API-Key": KEY}

BASE = "http://testserver"


@pytest.fixture
async def library(session: AsyncSession) -> Library:
    await make_user(session, user_id=1)
    await make_api_key(session, key=KEY, user_id=1)
    library = await get_library(session, LibraryType.USER, 1)
    await session.commit()
    return library


@pytest.fixture
async def article(session: AsyncSession, library: Library) -> Item:
    """The item `ZGKQRSGC` of the public group 2373134, field for field."""
    return await make_item(
        session,
        library,
        key="AAAA2345",
        item_type="journalArticle",
        fields={
            "title": (
                "Monoclonal antibodies specific to quail embryo tissues: their epitopes in "
                "the developing quail embryo and their application to identification of "
                "quail cells in quail-chick chimeras."
            ),
            "shortTitle": "Monoclonal antibodies specific to quail embryo tissues",
            "publicationTitle": "Journal of Histochemistry & Cytochemistry",
            "volume": "40",
            "issue": "11",
            "pages": "1769-1777",
            "date": "1992-11",
            "DOI": "10.1177/40.11.1385517",
            "ISSN": "0022-1554, 1551-5044",
            "url": "http://journals.sagepub.com/doi/10.1177/40.11.1385517",
            "accessDate": "2018-03-14T02:34:19Z",
            "language": "en",
            "libraryCatalog": "CrossRef",
        },
        creators=[
            ("author", "H", "Aoyama"),
            ("author", "K", "Asamoto"),
            ("author", "Y", "Nojyo"),
            ("author", "M", "Kinutani"),
        ],
    )


def render(
    response_format: str, item: Item, library: Library, tags: list[str] | None = None
) -> str:
    """Return one item written out, the way a one-item response is."""
    view = exportitem.export_item(item, library, BASE, [(name, 0) for name in tags or []])
    return exportformats.render(Format(response_format), [view])


class TestTheRegistry:
    def test_every_format_the_query_layer_accepts_can_be_written(self) -> None:
        """The two lists are apart because the query layer cannot import the
        formats without a cycle, so nothing but a test holds them together."""
        assert EXPORT_FORMATS | {Format.CSLJSON} == set(exportformats.kinds())

    def test_a_format_names_its_media_type_and_its_extension(self) -> None:
        assert exportformats.kind(Format.CSV).content_type == "text/csv;charset=UTF-8"
        assert exportformats.kind(Format.CSV).extension == "csv"


class TestRefer:
    async def test_an_article_is_written_tag_by_tag(self, library: Library, article: Item) -> None:
        written = render("refer", article, library, tags=["embryo"])

        assert written == (
            "%0 Journal Article\r\n"
            "%T Monoclonal antibodies specific to quail embryo tissues: their epitopes in the "
            "developing quail embryo and their application to identification of quail cells "
            "in quail-chick chimeras.\r\n"
            "%V 40\r\n"
            "%N 11\r\n"
            "%P 1769-1777\r\n"
            "%U http://journals.sagepub.com/doi/10.1177/40.11.1385517\r\n"
            "%G en\r\n"
            "%J Journal of Histochemistry & Cytochemistry\r\n"
            "%A Aoyama, H\r\n"
            "%A Asamoto, K\r\n"
            "%A Nojyo, Y\r\n"
            "%A Kinutani, M\r\n"
            "%D 1992-11\r\n"
            "%K embryo\r\n"
            "\r\n"
        )

    async def test_a_book_names_its_container_b_and_not_j(
        self, session: AsyncSession, library: Library
    ) -> None:
        """`%J` is a journal and nothing else is one, however it is stored."""
        chapter = await make_item(
            session,
            library,
            item_type="bookSection",
            fields={"title": "A chapter", "bookTitle": "A book", "publisher": "Elsevier"},
            creators=[("author", "Nari", "Jeon"), ("editor", "BT", "Semimetals")],
        )

        written = render("refer", chapter, library)

        assert "%B A book\r\n" in written
        assert "%J" not in written
        assert "%E Semimetals, BT\r\n" in written

    async def test_a_note_is_not_a_reference(self, session: AsyncSession, library: Library) -> None:
        note = await make_item(session, library, item_type="note", fields={"note": "<p>Hi</p>"})

        assert render("refer", note, library) == ""


class TestWikipedia:
    async def test_an_article_becomes_a_cite_journal_template(
        self, library: Library, article: Item
    ) -> None:
        written = render("wikipedia", article, library)

        assert written == (
            "{{Cite journal| doi = 10.1177/40.11.1385517| issn = 0022-1554, 1551-5044"
            "| volume = 40| issue = 11| pages = 1769–1777"  # noqa: RUF001
            "| last1 = Aoyama| first1 = H| last2 = Asamoto| first2 = K"
            "| last3 = Nojyo| first3 = Y| last4 = Kinutani| first4 = M"
            "| title = Monoclonal antibodies specific to quail embryo tissues: their epitopes "
            "in the developing quail embryo and their application to identification of quail "
            "cells in quail-chick chimeras.| journal = Journal of Histochemistry & Cytochemistry"
            "| access-date = 2018-03-14| date = 1992-11"
            "| url = http://journals.sagepub.com/doi/10.1177/40.11.1385517}}"
        )

    async def test_one_author_is_not_numbered(
        self, session: AsyncSession, library: Library
    ) -> None:
        book = await make_item(
            session,
            library,
            item_type="book",
            fields={"title": "Atom probe microscopy", "publisher": "Springer", "date": "2012"},
            creators=[("author", "Baptiste", "Gault")],
        )

        assert render("wikipedia", book, library) == (
            "{{Cite book| publisher = Springer| last = Gault| first = Baptiste"
            "| title = Atom probe microscopy| date = 2012}}"
        )

    async def test_a_chapter_names_the_book_as_the_title(
        self, session: AsyncSession, library: Library
    ) -> None:
        """`title` is the work the chapter is in; the chapter itself is
        `chapter`, which is what the template documents."""
        chapter = await make_item(
            session,
            library,
            item_type="bookSection",
            fields={"title": "A chapter", "bookTitle": "A book"},
        )

        written = render("wikipedia", chapter, library)

        assert "| title = A book" in written
        assert "| chapter = A chapter" in written


class TestCoins:
    async def test_an_article_becomes_a_journal_context_object(
        self, library: Library, article: Item
    ) -> None:
        written = render("coins", article, library)

        assert written == (
            "<span class='Z3988' title='url_ver=Z39.88-2004&amp;ctx_ver=Z39.88-2004"
            "&amp;rfr_id=info%3Asid%2Fzotero.org%3A2"
            "&amp;rft_id=info%3Adoi%2F10.1177%2F40.11.1385517"
            "&amp;rft_val_fmt=info%3Aofi%2Ffmt%3Akev%3Amtx%3Ajournal&amp;rft.genre=article"
            "&amp;rft.atitle=Monoclonal%20antibodies%20specific%20to%20quail%20embryo%20"
            "tissues%3A%20their%20epitopes%20in%20the%20developing%20quail%20embryo%20and%20"
            "their%20application%20to%20identification%20of%20quail%20cells%20in%20quail-"
            "chick%20chimeras.&amp;rft.jtitle=Journal%20of%20Histochemistry%20%26%20"
            "Cytochemistry&amp;rft.volume=40&amp;rft.issue=11&amp;rft.aufirst=H"
            "&amp;rft.aulast=Aoyama&amp;rft.au=H%20Aoyama&amp;rft.au=K%20Asamoto"
            "&amp;rft.au=Y%20Nojyo&amp;rft.au=M%20Kinutani&amp;rft.date=1992-11"
            "&amp;rft.pages=1769-1777&amp;rft.spage=1769&amp;rft.epage=1777"
            "&amp;rft.issn=0022-1554%2C%201551-5044&amp;rft.language=en'></span>\n"
        )

    async def test_everything_else_is_described_in_dublin_core(
        self, session: AsyncSession, library: Library
    ) -> None:
        page = await make_item(
            session,
            library,
            item_type="webpage",
            fields={"title": "A page", "url": "http://example.org/a"},
        )

        written = render("coins", page, library)

        assert "rft_val_fmt=info%3Aofi%2Ffmt%3Akev%3Amtx%3Adc" in written
        assert "rft.type=webpage" in written
        assert "rft.identifier=http%3A%2F%2Fexample.org%2Fa" in written

    async def test_even_a_note_gets_a_span(self, session: AsyncSession, library: Library) -> None:
        """Upstream writes one carrying nothing but the type, and a reader
        counting spans against items would otherwise come up short."""
        note = await make_item(session, library, item_type="note", fields={"note": "<p>Hi</p>"})

        assert render("coins", note, library).endswith("rft.type=note'></span>\n")


class TestBookmarks:
    async def test_an_item_with_a_url_becomes_a_bookmark(
        self, session: AsyncSession, library: Library
    ) -> None:
        page = await make_item(
            session,
            library,
            item_type="webpage",
            fields={"title": "A page", "url": "http://example.org/a"},
        )

        written = render("bookmarks", page, library, tags=["one", "two"])

        assert written.startswith("<!DOCTYPE NETSCAPE-Bookmark-file-1>\n")
        assert '    <DT><A HREF="http://example.org/a" TAGS="one,two">A page</A>\n' in written
        assert written.endswith("</DL>")

    async def test_an_item_with_no_url_is_not_a_bookmark(
        self, session: AsyncSession, library: Library
    ) -> None:
        book = await make_item(session, library, item_type="book", fields={"title": "A book"})

        assert "<DT>" not in render("bookmarks", book, library)

    async def test_the_markup_is_escaped(self, session: AsyncSession, library: Library) -> None:
        """Upstream writes the title and the URL raw, which makes a file no HTML
        parser reads back the way it went in -- and this server will answer
        `format=bookmarks` to a browser holding a key in the query string."""
        page = await make_item(
            session,
            library,
            item_type="webpage",
            fields={"title": "Bells & <whistles>", "url": "http://example.org/?a=1&b=2"},
        )

        written = render("bookmarks", page, library)

        assert (
            '<A HREF="http://example.org/?a=1&amp;b=2">Bells &amp; &lt;whistles&gt;</A>' in written
        )


class TestCsv:
    async def test_the_columns_are_the_ones_zotero_writes(
        self, library: Library, article: Item
    ) -> None:
        written = render("csv", article, library, tags=["embryo"])

        assert written.startswith("﻿")
        rows = list(csv.reader(io.StringIO(written.lstrip("﻿"))))
        assert rows[0][:6] == [
            "Key",
            "Item Type",
            "Publication Year",
            "Author",
            "Title",
            "Publication Title",
        ]
        cells = dict(zip(rows[0], rows[1], strict=True))
        assert cells["Key"] == "AAAA2345"
        assert cells["Publication Year"] == "1992"
        assert cells["Date"] == "1992-11"
        assert cells["Author"] == "Aoyama, H; Asamoto, K; Nojyo, Y; Kinutani, M"
        assert cells["Access Date"] == "2018-03-14 02:34:19"
        assert cells["Manual Tags"] == "embryo"
        assert cells["Library Catalog"] == "CrossRef"

    async def test_the_date_added_column_is_the_date_the_item_was_added(
        self, session: AsyncSession, library: Library, article: Item
    ) -> None:
        """Upstream's translation server writes `dateModified` into both date
        columns, which loses the one thing the column is for."""
        written = render("csv", article, library)

        rows = list(csv.reader(io.StringIO(written.lstrip("﻿"))))
        cells = dict(zip(rows[0], rows[1], strict=True))
        assert cells["Date Added"] == article.date_added.strftime("%Y-%m-%d %H:%M:%S")
        assert cells["Date Modified"] == article.date_modified.strftime("%Y-%m-%dT%H:%M:%SZ")

    async def test_a_note_has_no_row(self, session: AsyncSession, library: Library) -> None:
        note = await make_item(session, library, item_type="note", fields={"note": "<p>Hi</p>"})

        written = render("csv", note, library)

        assert written.count("\n") == 0


class TestRefWorks:
    async def test_an_article_is_written_tag_by_tag(self, library: Library, article: Item) -> None:
        written = render("refworks_tagged", article, library)

        assert written == (
            "RT Journal Article\r\n"
            "T1 Monoclonal antibodies specific to quail embryo tissues: their epitopes in the "
            "developing quail embryo and their application to identification of quail cells "
            "in quail-chick chimeras.\r\n"
            "A1 Aoyama, H\r\n"
            "A1 Asamoto, K\r\n"
            "A1 Nojyo, Y\r\n"
            "A1 Kinutani, M\r\n"
            "T2 Journal of Histochemistry & Cytochemistry\r\n"
            "FD 1992-11\r\n"
            "YR 1992\r\n"
            "DO 10.1177/40.11.1385517\r\n"
            "VO 40\r\n"
            "IS 11\r\n"
            "SP 1769\r\n"
            "OP 1777\r\n"
            "LA en\r\n"
            "SN 0022-1554, 1551-5044\r\n"
            "ST Monoclonal antibodies specific to quail embryo tissues\r\n"
            "UL http://journals.sagepub.com/doi/10.1177/40.11.1385517\r\n"
            "RD 2018/03/14/02:34:19\r\n"
            "\r\n\r\n"
        )

    async def test_one_tag_holds_a_different_field_per_item_type(
        self, session: AsyncSession, library: Library
    ) -> None:
        """`T2` is the journal of an article and the book a section is in; a
        book's own `T2` is its series, and its title stays in `T1`."""
        chapter = await make_item(
            session,
            library,
            item_type="bookSection",
            fields={"title": "A chapter", "bookTitle": "A book", "numPages": "300"},
        )

        written = render("refworks_tagged", chapter, library)

        assert "RT Book, Section\r\n" in written
        assert "T1 A chapter\r\n" in written
        assert "T2 A book\r\n" in written

    async def test_a_page_range_is_split_in_two(
        self, session: AsyncSession, library: Library
    ) -> None:
        """A single page is written as neither: the translator fills the value
        in only when the range matches, and an unset value is not written."""
        one = await make_item(
            session, library, item_type="journalArticle", fields={"pages": "1769"}
        )

        written = render("refworks_tagged", one, library)

        assert "SP " not in written
        assert "OP " not in written


class TestDublinCoreRdf:
    async def test_an_item_becomes_a_description(
        self, session: AsyncSession, library: Library
    ) -> None:
        book = await make_item(
            session,
            library,
            item_type="book",
            fields={
                "title": "Atom probe microscopy",
                "publisher": "Springer",
                "date": "2012",
                "ISBN": "9781461434368",
            },
            creators=[("author", "Baptiste", "Gault"), ("editor", "Ann", "Other")],
        )

        assert render("rdf_dc", book, library) == (
            '<rdf:RDF\n xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"'
            '\n xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
            '    <rdf:Description rdf:about="urn:isbn:9781461434368">\n'
            "        <dc:title>Atom probe microscopy</dc:title>\n"
            "        <dc:type>book</dc:type>\n"
            "        <dc:creator>Gault, Baptiste</dc:creator>\n"
            "        <dc:contributor>Other, Ann</dc:contributor>\n"
            "        <dc:publisher>Springer</dc:publisher>\n"
            "        <dc:date>2012</dc:date>\n"
            "        <dc:identifier>ISBN 9781461434368</dc:identifier>\n"
            "    </rdf:Description>\n"
            "</rdf:RDF>\n"
        )

    async def test_an_item_with_nothing_to_name_it_is_a_blank_node(
        self, session: AsyncSession, library: Library
    ) -> None:
        book = await make_item(session, library, item_type="book", fields={"title": "A book"})

        assert 'rdf:nodeID="item_1"' in render("rdf_dc", book, library)


class TestEvernote:
    async def test_an_item_becomes_a_note_carrying_its_metadata(
        self, session: AsyncSession, library: Library
    ) -> None:
        page = await make_item(
            session,
            library,
            item_type="webpage",
            fields={"title": "A page", "url": "http://example.org/a"},
        )

        written = render("evernote", page, library, tags=["one, two"])

        assert "<title>A page</title>" in written
        # A comma separates one tag from the next in Evernote.
        assert "<tag>one / two</tag>" in written
        assert "<source-url>http://example.org/a</source-url>" in written
        assert written.endswith("</en-export>\n")

    async def test_a_timestamp_ends_in_one_z(self, session: AsyncSession, library: Library) -> None:
        """Upstream appends a `Z` to `dateModified`, which already carries
        one, and writes `20260227T045900ZZ`."""
        book = await make_item(session, library, item_type="book", fields={"title": "A book"})

        written = render("evernote", book, library)

        assert "ZZ</updated>" not in written
        assert written.count("Z</updated>") == 1

    async def test_an_item_with_no_url_says_nothing_rather_than_undefined(
        self, session: AsyncSession, library: Library
    ) -> None:
        book = await make_item(session, library, item_type="book", fields={"title": "A book"})

        assert "<source-url></source-url>" in render("evernote", book, library)


class TestTheEndpoints:
    @pytest.mark.parametrize(
        ("response_format", "content_type", "marker"),
        [
            ("refer", "application/x-research-info-systems", "%0 Journal Article"),
            ("wikipedia", "text/x-wiki;charset=UTF-8", "{{Cite journal"),
            ("coins", "text/html;charset=UTF-8", "<span class='Z3988'"),
            ("bookmarks", "text/html;charset=UTF-8", "<TITLE>Bookmarks</TITLE>"),
            ("csv", "text/csv;charset=UTF-8", '"Key","Item Type"'),
        ],
    )
    async def test_a_listing_answers_in_the_format_asked_for(
        self,
        client: httpx.AsyncClient,
        library: Library,
        article: Item,
        response_format: str,
        content_type: str,
        marker: str,
    ) -> None:
        response = await client.get(f"/users/1/items?format={response_format}", headers=AUTH)

        assert response.status_code == 200
        assert response.headers["content-type"] == content_type
        assert marker in response.text

    async def test_one_item_answers_in_the_format_asked_for(
        self, client: httpx.AsyncClient, library: Library, article: Item
    ) -> None:
        response = await client.get("/users/1/items/AAAA2345?format=refer", headers=AUTH)

        assert response.status_code == 200
        assert response.text.startswith("%0 Journal Article")

    async def test_include_carries_one_document_per_item(
        self, client: httpx.AsyncClient, library: Library, article: Item
    ) -> None:
        body = (await client.get("/users/1/items?include=csv,refer", headers=AUTH)).json()

        assert body[0]["refer"].startswith("%0 Journal Article")
        assert body[0]["csv"].startswith('﻿"Key","Item Type"')
        assert "data" not in body[0]

    async def test_an_unknown_format_is_still_refused(
        self, client: httpx.AsyncClient, library: Library, article: Item
    ) -> None:
        response = await client.get("/users/1/items?format=endnote", headers=AUTH)

        assert response.status_code == 400
