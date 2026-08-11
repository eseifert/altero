"""Writing items out of the browser in the export formats.

The formats themselves are `altero/cite/export.py`, tested against the v3
endpoints in ``test_citations.py``. What is checked here is what only this door
has: a cookie instead of a key, that the file holds exactly what the list on
screen was showing, that reading a library is enough to take a copy of its
bibliography, and that an export longer than one batch is still one file with
one citation key per item.
"""

import json

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Library, LibraryType
from altero.services import admin
from tests import factories
from tests.test_web_routes import register


@pytest.fixture
async def ada(client: httpx.AsyncClient) -> httpx.AsyncClient:
    """One account, signed in, with its personal library."""
    assert (await register(client)).status_code == 201
    return client


async def personal_library(session: AsyncSession, owner_id: int = 1) -> Library:
    library = await session.scalar(
        select(Library).where(Library.type == LibraryType.USER, Library.owner_id == owner_id)
    )
    assert library is not None
    return library


async def export(client: httpx.AsyncClient, library: Library, **query: str) -> httpx.Response:
    parameters = "&".join(f"{name}={value}" for name, value in query.items())
    return await client.get(f"/web/libraries/{library.id}/items/export?{parameters}")


class TestWhatComesOut:
    async def test_a_library_is_written_as_bibtex(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library = await personal_library(session)
        await factories.make_item(
            session,
            library,
            fields={"title": "Structure and Interpretation", "date": "1985"},
            creators=[("author", "Harold", "Abelson")],
        )

        response = await export(ada, library, format="bibtex")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-bibtex")
        assert "@book{abelson1985structure," in response.text
        assert "Structure and Interpretation" in response.text

    async def test_biblatex_uses_its_own_entry_types(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The one thing that tells the two apart: BibTeX has no `@online`."""
        library = await personal_library(session)
        await factories.make_item(session, library, item_type="webpage", fields={"title": "A page"})

        bibtex = (await export(ada, library, format="bibtex")).text
        biblatex = (await export(ada, library, format="biblatex")).text

        assert "@misc{" in bibtex
        assert "@online{" in biblatex

    async def test_ris_is_written_as_ris(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library = await personal_library(session)
        await factories.make_item(session, library, fields={"title": "A book"})

        response = await export(ada, library, format="ris")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-research-info-systems")
        assert response.text.startswith("TY  - BOOK")
        assert "TI  - A book" in response.text

    async def test_csl_json_is_a_file_rather_than_the_api_s_envelope(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """A CSL JSON *file* is an array. The `{"items": …}` wrapper is the v3
        API's envelope, and pandoc and citeproc read neither of those."""
        library = await personal_library(session)
        await factories.make_item(session, library, fields={"title": "A book"})

        response = await export(ada, library, format="csljson")

        assert response.status_code == 200
        body = json.loads(response.text)
        assert isinstance(body, list)
        assert body[0]["title"] == "A book"

    async def test_the_file_is_named_and_offered_as_a_download(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library = await personal_library(session)
        await factories.make_item(session, library, fields={"title": "A book"})

        response = await export(ada, library, format="bibtex", name="My%20Library")

        disposition = response.headers["content-disposition"]
        assert disposition.startswith("attachment;")
        assert "My%20Library.bib" in disposition

    async def test_a_name_cannot_carry_a_path_or_break_the_header(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library = await personal_library(session)
        await factories.make_item(session, library, fields={"title": "A book"})

        response = await export(ada, library, format="ris", name='../../etc/"passwd')

        disposition = response.headers["content-disposition"]
        assert "/" not in disposition.split("filename")[1]
        assert response.status_code == 200

    async def test_an_empty_view_writes_an_empty_file_rather_than_failing(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The desktop client greys the menu item out instead; so does the
        interface. A request made anyway gets an empty bibliography, which is
        what an empty library has."""
        library = await personal_library(session)

        response = await export(ada, library, format="bibtex")

        assert response.status_code == 200
        assert response.text.strip() == ""


class TestWhichItems:
    async def test_a_collection_narrows_it_to_that_collection(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library = await personal_library(session)
        inside = await factories.make_item(session, library, fields={"title": "Filed"})
        await factories.make_item(session, library, fields={"title": "Loose"})
        collection = await factories.make_collection(session, library, items=[inside])

        text = (await export(ada, library, format="ris", collection=collection.key)).text

        assert "Filed" in text
        assert "Loose" not in text

    async def test_a_search_narrows_it_the_way_the_list_is_narrowed(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library = await personal_library(session)
        await factories.make_item(session, library, fields={"title": "Whales"})
        await factories.make_item(session, library, fields={"title": "Trains"})

        text = (await export(ada, library, format="ris", q="Whales")).text

        assert "Whales" in text
        assert "Trains" not in text

    async def test_a_tag_narrows_it_too(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library = await personal_library(session)
        tagged = await factories.make_item(session, library, fields={"title": "Tagged"})
        await factories.make_item(session, library, fields={"title": "Untagged"})
        await factories.tag_item(session, library, tagged, "to read")

        text = (await export(ada, library, format="ris", tag="to%20read")).text

        assert "Tagged" in text
        assert "Untagged" not in text

    async def test_named_items_are_the_only_ones_written(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """A selection is an errand of its own, as it is for filing and trashing."""
        library = await personal_library(session)
        first = await factories.make_item(session, library, fields={"title": "Chosen"})
        await factories.make_item(session, library, fields={"title": "Passed over"})

        text = (await export(ada, library, format="ris", itemKey=first.key)).text

        assert "Chosen" in text
        assert "Passed over" not in text

    async def test_a_key_from_another_library_is_not_reached(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library = await personal_library(session)
        await factories.make_item(session, library, fields={"title": "Mine"})
        grace = await admin.create_user(session, username="grace")
        elsewhere = await personal_library(session, owner_id=grace.id)
        theirs = await factories.make_item(session, elsewhere, fields={"title": "Theirs"})

        text = (await export(ada, library, format="ris", itemKey=theirs.key)).text

        assert "Theirs" not in text
        assert text.strip() == ""

    async def test_notes_and_attachments_are_left_out(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Neither has a bibliography entry, and altero has no note translator
        to write one with. The desktop client's own BibTeX and RIS translators
        skip them."""
        library = await personal_library(session)
        await factories.make_item(session, library, fields={"title": "A book"})
        await factories.make_item(
            session, library, item_type="note", fields={"note": "<p>A thought</p>"}
        )
        await factories.make_item(
            session,
            library,
            item_type="attachment",
            fields={"title": "A scan", "linkMode": "linked_url", "url": "https://example.org"},
        )

        text = (await export(ada, library, format="ris", scope="all")).text

        assert "A book" in text
        assert "A thought" not in text
        assert "A scan" not in text

    async def test_the_trash_is_out_of_the_way_unless_it_is_what_is_shown(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library = await personal_library(session)
        await factories.make_item(session, library, fields={"title": "Kept"})
        await factories.make_item(session, library, fields={"title": "Thrown away"}, deleted=True)

        library_text = (await export(ada, library, format="ris")).text
        trash_text = (await export(ada, library, format="ris", scope="trash")).text

        assert "Kept" in library_text
        assert "Thrown away" not in library_text
        assert "Thrown away" in trash_text
        assert "Kept" not in trash_text

    async def test_more_items_than_one_batch_all_arrive_with_distinct_keys(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The export is written in batches, and a citation key is unique
        within a file — so the set of used keys has to outlive one batch."""
        from altero.services import itemexport

        library = await personal_library(session)
        count = itemexport.BATCH + 5
        for _ in range(count):
            await factories.make_item(
                session,
                library,
                fields={"title": "Cetacean acoustics", "date": "1994"},
                creators=[("author", "Ada", "Lovelace")],
            )

        text = (await export(ada, library, format="bibtex", scope="all")).text

        keys = [
            line.split("{")[1].rstrip(",") for line in text.splitlines() if line.startswith("@")
        ]
        assert len(keys) == count
        assert len(set(keys)) == count


class TestWhoMay:
    async def test_a_session_is_required(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        library = await personal_library(session)
        client.cookies.clear()

        assert (await export(client, library, format="ris")).status_code == 401

    async def test_reading_a_group_is_enough_to_export_it(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Unlike an archive, which is an administrator's act: this file holds
        nothing a member could not read item by item."""
        grace = await admin.create_user(session, username="grace")
        group = await factories.make_group(session, owner_id=grace.id, members={1: "member"})
        await factories.make_item(session, group, fields={"title": "Shared reading"})

        response = await export(ada, group, format="ris")

        assert response.status_code == 200
        assert "Shared reading" in response.text

    async def test_a_library_this_account_cannot_read_is_refused(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        grace = await admin.create_user(session, username="grace")
        theirs = await personal_library(session, owner_id=grace.id)

        assert (await export(ada, theirs, format="ris")).status_code == 403

    async def test_a_missing_library_is_404(self, ada: httpx.AsyncClient) -> None:
        response = await ada.get("/web/libraries/9999/items/export?format=ris")

        assert response.status_code == 404

    async def test_an_api_key_is_not_a_way_in(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        library = await personal_library(session)
        key = await admin.create_api_key(session, username="ada", name="laptop")
        client.cookies.clear()

        response = await client.get(
            f"/web/libraries/{library.id}/items/export?format=ris",
            headers={"Zotero-API-Key": key.key},
        )

        assert response.status_code == 401


class TestWhatItRefuses:
    async def test_an_unknown_format_is_refused(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library = await personal_library(session)

        response = await export(ada, library, format="endnote")

        assert response.status_code == 400

    async def test_a_reading_format_is_not_an_export_format(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """`json` and `atom` are how the API describes an item, not files to
        hand to another program."""
        library = await personal_library(session)

        assert (await export(ada, library, format="json")).status_code == 400
        assert (await export(ada, library, format="atom")).status_code == 400

    async def test_a_sort_the_list_cannot_do_is_refused(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library = await personal_library(session)

        assert (await export(ada, library, format="ris", sort="colour")).status_code == 400

    async def test_a_group_has_no_publications_to_export(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        grace = await admin.create_user(session, username="grace")
        group = await factories.make_group(session, owner_id=grace.id, members={1: "member"})

        response = await export(ada, group, format="ris", scope="publications")

        assert response.status_code == 400
