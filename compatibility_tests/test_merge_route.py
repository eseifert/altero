"""Real HTTP: browser uploads, PDF text deduplication, then incremental API reads.

The actual desktop scenario remains P4.4; this drives the browser endpoint and
checks what a syncing client can subsequently download.
"""

import httpx2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests import factories
from tests.test_pdfmerge import TEXT, pdf_bytes
from tests.test_web_merge import seed
from tests.test_web_routes import csrf_headers, register

from altero.models import Library


async def test_merge_route_preserves_uploaded_pdf_and_annotation_over_http(
    session: AsyncSession, socket_client: httpx2.AsyncClient
) -> None:
    client = socket_client
    assert (await register(client)).status_code == 201
    library = await session.scalar(select(Library).where(Library.owner_id == 1))
    assert library is not None
    case = await seed(session, library)
    key = await factories.make_api_key(session)
    api_headers = {"Zotero-API-Key": key.key}
    attachments = []
    original = pdf_bytes()
    for parent, body in (
        (case.master.key, original),
        (case.other.key, pdf_bytes(" ".join(reversed(TEXT.split())))),
    ):
        response = await client.post(
            f"/web/libraries/{library.id}/attachments",
            params={"filename": "paper.pdf", "parentItem": parent},
            headers=csrf_headers(client) | {"Content-Type": "application/pdf"},
            content=body,
        )
        assert response.status_code == 201
        attachments.append(response.json())
    kept, removed = attachments
    assert kept["data"]["md5"] != removed["data"]["md5"]
    created = await client.post(
        "/users/1/items",
        headers=api_headers,
        json=[
            {
                "itemType": "annotation",
                "parentItem": removed["key"],
                "annotationType": "highlight",
                "annotationText": "Excerpt",
                "annotationComment": "A comment",
                "annotationColor": "#ff0000",
                "annotationSortIndex": "00000|000000|00000",
                "annotationPosition": '{"pageIndex":0,"rects":[[10,10,20,20]]}',
            }
        ],
    )
    assert created.status_code == 200
    assert created.json()["failed"] == {}
    annotation = created.json()["successful"]["0"]["key"]
    libraries = (await client.get("/web/libraries")).json()
    before = next(row["version"] for row in libraries if row["id"] == library.id)
    headers = csrf_headers(client) | {"If-Unmodified-Since-Version": str(before)}
    response = await client.post(
        case.url, headers=headers, json=case.body(fields={"title": "Chosen"})
    )
    assert response.status_code == 200
    changed = {item["key"]: item["data"] for item in response.json()["items"]}
    assert changed[case.master.key]["title"] == "Chosen"
    assert changed[case.other.key]["deleted"] == 1
    assert changed[removed["key"]]["deleted"] == 1
    assert changed[annotation]["parentItem"] == kept["key"]
    assert {item["version"] for item in changed.values()} == {before + 1}
    incremental = await client.get(
        f"/users/1/items?since={before}&includeTrashed=1&format=versions", headers=api_headers
    )
    assert incremental.json() == {item: before + 1 for item in changed}
    download = await client.get(
        f"/users/1/items/{kept['key']}/file", headers=api_headers, follow_redirects=True
    )
    assert download.status_code == 200
    assert download.content == original
    # Replaying the old page must not merge again or take another version.
    replay = await client.post(case.url, headers=headers, json=case.body())
    assert replay.status_code == 412
    libraries = (await client.get("/web/libraries")).json()
    assert next(row["version"] for row in libraries if row["id"] == library.id) == before + 1
