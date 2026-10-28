"""Unequal-size archives of one page race through actual authorization, upload and registration.

Each is stored under its own digest, as upstream stores it, so neither replaces
the other and both attachments register and download what their client sent.
"""

import hashlib
import io
import zipfile

import httpx2

from tools.compatibility.runtime import disposable_server


async def test_unequal_archives_of_one_page_are_each_kept(tmp_path):
    content = b"<html>same main file</html>"
    digest = hashlib.md5(content, usedforsecurity=False).hexdigest()
    archives = []
    for comment in (b"different ZIP metadata" * 100, b""):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("page.html", content)
            archive.comment = comment
        archives.append(output.getvalue())
    assert len(archives[0]) > len(archives[1])
    async with (
        disposable_server(tmp_path / "server") as server,
        httpx2.AsyncClient(base_url=server.url, headers={"Zotero-API-Key": server.key}) as client,
    ):
        keys = ("ZIPBIG23", "ZIPSMAL2")
        seeded = await client.post(
            "/users/1/items",
            json=[
                dict(
                    key=key,
                    itemType="attachment",
                    linkMode="imported_file",
                    filename="page.html",
                    contentType="text/html",
                )
                for key in keys
            ],
        )
        assert not seeded.json()["failed"]
        permissions = []
        for key, body in zip(keys, archives, strict=True):
            authorization = await client.post(
                f"/users/1/items/{key}/file",
                headers={"If-None-Match": "*"},
                data=dict(
                    md5=digest,
                    filename="page.html",
                    filesize=str(len(body)),
                    mtime="1785701798544",
                    zipMD5=hashlib.md5(body, usedforsecurity=False).hexdigest(),
                    zipFilename=key + ".zip",
                ),
            )
            assert authorization.status_code == 200
            permissions.append(authorization.json())
        for permission, body in zip(permissions, archives, strict=True):
            assert (await client.post(permission["url"], content=body)).status_code == 201
        for key, permission in zip(keys, permissions, strict=True):
            registered = await client.post(
                f"/users/1/items/{key}/file",
                headers={"If-None-Match": "*"},
                data=dict(upload=permission["uploadKey"]),
            )
            assert registered.status_code == 204
        for key, body in zip(keys, archives, strict=True):
            downloaded = await client.get(f"/users/1/items/{key}/file", follow_redirects=True)
            assert downloaded.content == body
            with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
                assert archive.testzip() is None
                assert archive.read("page.html") == content
