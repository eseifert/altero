"""The merge service's result as a syncing client reads it over real HTTP.

This is not desktop acceptance or the browser merge route; those have their
own roadmap tasks. It verifies the versioned graph and actual downloadable
bytes at the service/API boundary.
"""

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession
from tests import factories
from tests.test_merge_attachments import attachment
from tests.test_pdfmerge import pdf_bytes

from altero.models import LibraryType
from altero.services import merge, writes
from altero.services.auth import get_library
from altero.settings import Settings


async def test_merged_graph_and_files_are_readable_over_live_http(
    session: AsyncSession, socket_client: httpx2.AsyncClient, settings: Settings
) -> None:
    await factories.make_user(session)
    key = await factories.make_api_key(session)
    library = await get_library(session, LibraryType.USER, 1)
    library.version = 10
    await session.commit()
    master, other = [await factories.make_item(session, library) for _ in range(2)]
    kept = await attachment(session, library, master, settings.storage_path)
    removed = await attachment(session, library, other, settings.storage_path)
    annotation = await factories.make_item(
        session,
        library,
        item_type="annotation",
        parent=removed,
        fields={
            "annotationType": "highlight",
            "annotationText": "Excerpt",
            "annotationComment": "A comment",
            "annotationColor": "#ff0000",
            "annotationSortIndex": "00000|000000|00000",
            "annotationPosition": '{"pageIndex":0,"rects":[[10,10,20,20]]}',
        },
    )
    await writes.lock_library(session, library)
    version = await writes.bump_library_version(session, library)
    changed = await merge.merge_items(
        session, library, master, [other], version, storage_root=settings.storage_path
    )
    await session.commit()

    headers = {"Zotero-API-Key": key.key}
    response = await socket_client.get("/users/1/items?since=10&includeTrashed=1", headers=headers)
    assert response.status_code == 200
    assert int(response.headers["Last-Modified-Version"]) == version == 11
    by_key = {item["key"]: item["data"] for item in response.json()}
    assert set(by_key) == {item.key for item in changed}
    assert {item["version"] for item in by_key.values()} == {version}
    assert by_key[other.key]["deleted"] == 1
    assert by_key[removed.key]["deleted"] == 1
    assert by_key[annotation.key]["parentItem"] == kept.key
    assert by_key[kept.key]["relations"]["dc:replaces"].endswith("/" + removed.key)
    assert by_key[master.key]["relations"]["dc:replaces"].endswith("/" + other.key)
    download = await socket_client.get(
        f"/users/1/items/{kept.key}/file", headers=headers, follow_redirects=True
    )
    assert download.status_code == 200
    assert download.content == pdf_bytes()
