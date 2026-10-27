"""What may be the parent of what.

Upstream's rules, which the desktop client applies to itself before it uploads
(`Zotero.Item.prototype._saveData`): only notes, attachments and annotations
are children; a note or attachment hangs off a regular item, except an
embedded image, which may hang off a note; an annotation hangs off a file
attachment of a kind its reader opens -- a highlight, underline or note on a
PDF, an EPUB or an HTML snapshot, anything else on a PDF alone.

They are asked when an item is created or moved, not when one is re-sent
unchanged: an item a laxer server once stored under the wrong parent keeps
syncing rather than failing on every edit.
"""

from typing import Any

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Library, LibraryType
from altero.services.auth import get_library
from tests.factories import make_api_key, make_item, make_user

KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"
JSON = {"Zotero-API-Key": KEY, "Content-Type": "application/json"}

PDF = "application/pdf"
EPUB = "application/epub+zip"
HTML = "text/html"


@pytest.fixture
async def library(session: AsyncSession) -> Library:
    await make_user(session, user_id=1)
    await make_api_key(session, key=KEY, user_id=1)
    library = await get_library(session, LibraryType.USER, 1)
    library.version = 10
    await session.commit()
    return library


async def post(client: httpx2.AsyncClient, *objects: dict[str, Any]) -> dict[str, Any]:
    response = await client.post("/users/1/items", headers=JSON, json=list(objects))
    assert response.status_code == 200, response.text
    return dict(response.json())


async def made(client: httpx2.AsyncClient, item: dict[str, Any]) -> str:
    """Create ``item`` and return its key, failing the test if it was refused."""
    body = await post(client, item)
    assert body["failed"] == {}, body["failed"]
    return str(body["successful"]["0"]["key"])


async def book(client: httpx2.AsyncClient) -> str:
    return await made(client, {"itemType": "book", "title": "Parent"})


async def file(
    client: httpx2.AsyncClient,
    parent: str | None = None,
    content_type: str = PDF,
    link_mode: str = "imported_file",
) -> str:
    attachment: dict[str, Any] = {
        "itemType": "attachment",
        "linkMode": link_mode,
        "contentType": content_type,
    }
    if parent:
        attachment["parentItem"] = parent
    return await made(client, attachment)


def annotation(parent: str | None, annotation_type: str = "highlight") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "itemType": "annotation",
        "annotationType": annotation_type,
        "annotationColor": "#ffd400",
        "annotationSortIndex": "00001|000000|00000",
        "annotationPosition": '{"pageIndex":0,"rects":[[0,0,1,1]]}',
    }
    if annotation_type in ("highlight", "underline"):
        payload["annotationText"] = "a passage"
    if parent:
        payload["parentItem"] = parent
    return payload


def failure(body: dict[str, Any]) -> dict[str, Any]:
    assert body["successful"] == {}, body["successful"]
    return dict(body["failed"]["0"])


class TestWhatMayHaveAParent:
    async def test_an_item_cannot_be_its_own_parent(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        body = await post(client, {"key": "AAAA2345", "itemType": "note", "parentItem": "AAAA2345"})

        refused = failure(body)
        assert refused["code"] == 400
        assert refused["message"].startswith("Item AAAA2345 cannot be a child of itself")

    async def test_a_regular_item_cannot_have_a_parent(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        """Upstream fails this with a 500; it is the client's mistake, so 400."""
        parent = await book(client)

        refused = failure(await post(client, {"itemType": "book", "parentItem": parent}))

        assert refused["code"] == 400

    async def test_saying_a_regular_item_has_no_parent_is_fine(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        await made(client, {"itemType": "book", "parentItem": False})


class TestNotes:
    async def test_a_note_goes_under_a_regular_item(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        await made(client, {"itemType": "note", "parentItem": await book(client), "note": "x"})

    async def test_a_note_cannot_go_under_a_note(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        parent = await made(client, {"itemType": "note", "note": "standalone"})

        refused = failure(await post(client, {"itemType": "note", "parentItem": parent}))

        # Upstream's shape, `data` included: the same 409 the desktop reads for
        # a missing parent, which here finds the parent present and stops.
        assert refused == {
            "code": 409,
            "message": "Parent item cannot be a note or attachment",
            "data": {"parentItem": parent},
        }

    async def test_a_note_cannot_go_under_an_attachment(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        parent = await file(client)

        refused = failure(await post(client, {"itemType": "note", "parentItem": parent}))

        assert refused["code"] == 409

    async def test_a_note_cannot_be_moved_under_a_note(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        note = await made(client, {"itemType": "note", "note": "moving"})
        other = await made(client, {"itemType": "note", "note": "standalone"})

        refused = failure(await post(client, {"key": note, "version": 11, "parentItem": other}))

        assert refused["code"] == 409


class TestAttachments:
    async def test_an_attachment_goes_under_a_regular_item(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        await file(client, await book(client))

    async def test_an_attachment_cannot_go_under_a_child_attachment(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        child = await file(client, await book(client))

        refused = failure(
            await post(
                client,
                {"itemType": "attachment", "linkMode": "imported_file", "parentItem": child},
            )
        )

        assert refused["code"] == 400
        assert refused["message"] == f"Parent item {child} cannot be a child attachment"

    async def test_a_file_cannot_go_under_a_note(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        note = await made(client, {"itemType": "note", "note": "standalone"})

        refused = failure(
            await post(
                client,
                {"itemType": "attachment", "linkMode": "imported_file", "parentItem": note},
            )
        )

        assert refused["code"] == 409

    async def test_an_embedded_image_goes_under_a_note(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        """How an image pasted into a note is stored."""
        note = await made(client, {"itemType": "note", "note": "<p><img/></p>"})

        await file(client, note, content_type="image/png", link_mode="embedded_image")

    async def test_an_embedded_image_goes_under_a_child_note(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        note = await made(
            client, {"itemType": "note", "parentItem": await book(client), "note": "<p/>"}
        )

        await file(client, note, content_type="image/png", link_mode="embedded_image")


class TestAnnotations:
    async def test_an_annotation_must_have_a_parent(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        refused = failure(await post(client, annotation(None)))

        assert refused["code"] == 400
        assert refused["message"] == "Annotation item must have a parent item"

    async def test_an_annotation_cannot_go_under_a_regular_item(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        refused = failure(await post(client, annotation(await book(client))))

        assert refused["code"] == 400
        assert "must be a file attachment" in refused["message"]

    async def test_an_annotation_cannot_go_under_a_link(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        link = await made(
            client,
            {"itemType": "attachment", "linkMode": "linked_url", "url": "https://example.org/"},
        )

        refused = failure(await post(client, annotation(link)))

        assert refused["code"] == 400

    @pytest.mark.parametrize("annotation_type", ["highlight", "underline", "note"])
    @pytest.mark.parametrize("content_type", [PDF, EPUB, HTML])
    async def test_a_text_annotation_goes_on_any_file_a_reader_opens(
        self, client: httpx2.AsyncClient, library: Library, annotation_type: str, content_type: str
    ) -> None:
        parent = await file(client, await book(client), content_type=content_type)

        await made(client, annotation(parent, annotation_type))

    @pytest.mark.parametrize("annotation_type", ["image", "ink", "text"])
    async def test_a_drawn_annotation_goes_on_a_pdf(
        self, client: httpx2.AsyncClient, library: Library, annotation_type: str
    ) -> None:
        parent = await file(client, await book(client), content_type=PDF)

        await made(client, annotation(parent, annotation_type))

    @pytest.mark.parametrize("annotation_type", ["image", "ink", "text"])
    @pytest.mark.parametrize("content_type", [EPUB, HTML])
    async def test_a_drawn_annotation_goes_on_a_pdf_alone(
        self, client: httpx2.AsyncClient, library: Library, annotation_type: str, content_type: str
    ) -> None:
        parent = await file(client, await book(client), content_type=content_type)

        refused = failure(await post(client, annotation(parent, annotation_type)))

        assert refused["code"] == 400
        assert "must be a PDF" in refused["message"]

    async def test_a_highlight_cannot_go_on_a_plain_text_file(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        parent = await file(client, await book(client), content_type="text/plain")

        refused = failure(await post(client, annotation(parent)))

        assert refused["code"] == 400
        assert refused["message"].endswith("must be a PDF, EPUB, or HTML attachment")

    async def test_an_annotation_moved_to_an_epub_is_checked_too(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        parent = await book(client)
        pdf = await file(client, parent, content_type=PDF)
        epub = await file(client, parent, content_type=EPUB)
        ink = await made(client, annotation(pdf, "ink"))

        refused = failure(await post(client, {"key": ink, "version": 14, "parentItem": epub}))

        assert refused["code"] == 400


class TestWhatIsAlreadyStored:
    async def test_an_item_re_sent_under_the_parent_it_has_is_not_refused(
        self, client: httpx2.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        """A graph a laxer server once accepted keeps syncing.

        A note under a note, stored before these rules: an edit that leaves the
        parent where it is goes through, as it would on zotero.org, which asks
        a note about its parent only when the note is created.
        """
        parent = await make_item(session, library, key="AAAA2345", item_type="note")
        await make_item(
            session, library, key="BBBB2345", item_type="note", parent=parent, version=10
        )
        await session.commit()

        body = await post(
            client,
            {"key": "BBBB2345", "version": 10, "parentItem": "AAAA2345", "note": "edited"},
        )

        assert body["failed"] == {}
