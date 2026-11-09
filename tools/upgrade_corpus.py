"""A small, deterministic library carried through each tagged-beta upgrade."""

import copy
import hashlib
import io
import zipfile

import httpx2

PLAIN = b"Preserve these attachment bytes through the upgrade.\n"
PAGE = b"<html><body>Preserved snapshot</body></html>"
NOTE = '<div data-schema-version="9"><p dir="rtl">An unchanged note: שלום</p></div>'
PREFIXES = ("/users/1", "/groups/2")


def snapshot_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in (("page.html", PAGE), ("assets/style.css", b"body {color: navy}")):
            archive.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), content)
    return buffer.getvalue()


def md5(content: bytes) -> str:
    return hashlib.md5(content, usedforsecurity=False).hexdigest()


async def request(client: httpx2.AsyncClient, method: str, path: str, status=200, **kwargs):
    response = await client.request(method, path, **kwargs)
    assert response.status_code == status, f"{method} {path}: HTTP {response.status_code}"
    return response


async def batch(client: httpx2.AsyncClient, path: str, entries: list[dict]) -> None:
    body = (await request(client, "POST", path, json=entries)).json()
    assert body["failed"] == {}, body["failed"]
    assert len(body["successful"]) == len(entries)


async def populate(client: httpx2.AsyncClient, *, legacy_child_memberships: bool = False) -> None:
    for prefix in PREFIXES:
        await batch(
            client,
            f"{prefix}/collections",
            [
                {"key": "AAAA2345", "name": "Papers"},
                {"key": "BBBB2345", "name": "Nested", "parentCollection": "AAAA2345"},
            ],
        )
        await batch(
            client,
            f"{prefix}/items",
            [
                {
                    "key": "BKKK2345",
                    "itemType": "book",
                    "title": "Über preserved books",
                    "creators": [
                        {"creatorType": "author", "firstName": "Ada", "lastName": "Lovelace"}
                    ],
                    "tags": [{"tag": "upgrade"}],
                    "collections": ["BBBB2345"],
                    "inPublications": prefix == "/users/1",
                },
                {
                    "key": "NNTT2345",
                    "itemType": "note",
                    "parentItem": "BKKK2345",
                    "note": NOTE,
                    # Only older releases accept the invalid state that the
                    # child-membership migration must repair.
                    "collections": ["AAAA2345"] if legacy_child_memberships else [],
                },
                {
                    "key": "FILE2345",
                    "itemType": "attachment",
                    "parentItem": "BKKK2345",
                    "linkMode": "imported_file",
                    "filename": "paper.txt",
                    "contentType": "text/plain",
                },
                {
                    "key": "SNAP2345",
                    "itemType": "attachment",
                    "parentItem": "BKKK2345",
                    "linkMode": "imported_url",
                    "filename": "page.html",
                    "contentType": "text/html",
                },
                {"key": "TRSH2345", "itemType": "book", "title": "Still in trash", "deleted": True},
                {"key": "DEAD2345", "itemType": "book", "title": "Deleted before upgrade"},
            ],
        )
        await batch(
            client,
            f"{prefix}/searches",
            [
                {
                    "key": "SRCH2345",
                    "name": "Tagged books",
                    "conditions": [{"condition": "tag", "operator": "is", "value": "upgrade"}],
                }
            ],
        )
        await request(
            client,
            "PUT",
            f"{prefix}/settings/tagColors",
            204,
            json={"value": [{"name": "upgrade", "color": "#cc0000"}]},
        )
        watermark = (await request(client, "GET", f"{prefix}/items")).headers[
            "Last-Modified-Version"
        ]
        await request(
            client,
            "DELETE",
            f"{prefix}/items?itemKey=DEAD2345",
            204,
            headers={"If-Unmodified-Since-Version": watermark},
        )
        for key, content, filename, original in (
            ("FILE2345", PLAIN, "paper.txt", PLAIN),
            ("SNAP2345", snapshot_zip(), "page.html", PAGE),
        ):
            path = f"{prefix}/items/{key}/file"
            form = {
                "md5": md5(original),
                "filename": filename,
                "filesize": str(len(content)),
                "mtime": "1700000000000",
            }
            if key == "SNAP2345":
                form |= {"zipMD5": md5(content), "zipFilename": "snapshot.zip"}
            authorised = (
                await request(client, "POST", path, headers={"If-None-Match": "*"}, data=form)
            ).json()
            if authorised.get("exists"):
                continue
            await request(client, "POST", authorised["url"], 201, content=content)
            await request(client, "POST", path, 204, data={"upload": authorised["uploadKey"]})
        await request(
            client,
            "PUT",
            f"{prefix}/items/FILE2345/fulltext",
            204,
            json={
                "content": "Unique trigram needle: palimpsest",
                "indexedPages": 1,
                "totalPages": 1,
            },
        )


async def snapshot(client: httpx2.AsyncClient) -> dict:
    from tools.upgrade_paths import READER_KEY

    result: dict = {}
    for prefix in PREFIXES:
        library: dict = {}
        for endpoint in ("items", "items/trash", "collections", "searches"):
            response = await request(client, "GET", f"{prefix}/{endpoint}?limit=100")
            library[endpoint] = {entry["key"]: entry["data"] for entry in response.json()}
            # Current serializers send [] for empty creators; older ones omit it.
            # This is an API shape fix, not a migration of the stored item.
            for data in library[endpoint].values():
                if data.get("creators") == []:
                    data.pop("creators")
            library["version"] = int(response.headers["Last-Modified-Version"])
        for endpoint in ("settings", "deleted?since=0", "fulltext", "items/FILE2345/fulltext"):
            library[endpoint] = (await request(client, "GET", f"{prefix}/{endpoint}")).json()
        library["search"] = sorted(
            entry["key"]
            for entry in (
                await request(client, "GET", f"{prefix}/items?q=palimpsest&qmode=everything")
            ).json()
        )
        assert library["search"] == ["FILE2345"], "Populated full text must be searchable"
        assert library["items"]["NNTT2345"]["note"] == NOTE, "Note HTML changed"
        for key, content in (("FILE2345", PLAIN), ("SNAP2345", snapshot_zip())):
            redirect = await request(client, "GET", f"{prefix}/items/{key}/file", 302)
            # The redirected download must not need the API credential.
            async with httpx2.AsyncClient(trust_env=False) as anonymous:
                download = await request(anonymous, "GET", redirect.headers["Location"])
            assert download.content == content, f"{prefix}/{key}: attachment bytes changed"
            library[key] = {
                name: redirect.headers[name]
                for name in (
                    "Zotero-File-MD5",
                    "Zotero-File-Modification-Time",
                    "Zotero-File-Compressed",
                )
            }
        result[prefix] = library
    result["groups"] = [
        entry["data"] for entry in (await request(client, "GET", "/users/1/groups")).json()
    ]
    headers = {"Zotero-API-Key": READER_KEY}
    readable = await request(client, "GET", "/groups/2/items", headers=headers)
    assert {entry["key"] for entry in readable.json()} == set(result["/groups/2"]["items"])
    await request(client, "GET", "/users/1/items", 403, headers=headers)
    await request(
        client,
        "POST",
        "/groups/2/items",
        403,
        headers=headers,
        json=[{"itemType": "book", "title": "Must not create"}],
    )
    return result


def check_preserved(before: dict, after: dict) -> None:
    expected = copy.deepcopy(before)
    for prefix in PREFIXES:
        if prefix not in expected:
            continue
        library = expected[prefix]
        note = library["items"]["NNTT2345"]
        if note.get("collections"):
            # The documented repair removes invalid child memberships and
            # advances exactly the affected item and library once.
            library["version"] += 1
            note["collections"] = []
            note["version"] = library["version"]
            if prefix == "/groups/2":
                for group in expected["groups"]:
                    if group["id"] == 2:
                        group["version"] = library["version"]
    assert after == expected, "Upgrade changed persisted library data or versions"


async def check_new_writes(client: httpx2.AsyncClient, before: dict) -> None:
    for prefix in PREFIXES:
        version = before[prefix]["version"]
        response = await request(
            client,
            "POST",
            f"{prefix}/items",
            json=[
                {
                    "key": "BKKK2345",
                    "version": before[prefix]["items"]["BKKK2345"]["version"],
                    "title": "Written after upgrade",
                }
            ],
        )
        assert response.json()["failed"] == {}
        assert int(response.headers["Last-Modified-Version"]) == version + 1
        item = (await request(client, "GET", f"{prefix}/items/BKKK2345")).json()["data"]
        assert item["title"] == "Written after upgrade"
        assert item["version"] == version + 1
        assert item["creators"] == before[prefix]["items"]["BKKK2345"]["creators"]
        stale = await client.post(
            f"{prefix}/items",
            headers={"If-Unmodified-Since-Version": str(version)},
            json=[{"key": "BKKK2345", "title": "Must refuse stale write"}],
        )
        assert stale.status_code == 412
