"""Unequal-size archives race through actual authorization, upload and registration."""

import hashlib
import io
import zipfile

import httpx

from tools.compatibility.runtime import disposable_server


async def test_smaller_whole_archive_survives_the_other_uploads_registration(tmp_path):
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
        httpx.AsyncClient(base_url=server.url, headers={"Zotero-API-Key": server.key}) as client,
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
        refused = await client.post(
            f"/users/1/items/{keys[0]}/file",
            headers={"If-None-Match": "*"},
            data=dict(upload=permissions[0]["uploadKey"]),
        )
        assert refused.status_code == 400
        accepted = await client.post(
            f"/users/1/items/{keys[1]}/file",
            headers={"If-None-Match": "*"},
            data=dict(upload=permissions[1]["uploadKey"]),
        )
        assert accepted.status_code == 204, "Refused registration removed another complete archive"
        downloaded = await client.get(f"/users/1/items/{keys[1]}/file", follow_redirects=True)
        assert downloaded.content == archives[1]
        with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
            assert archive.testzip() is None
            assert archive.read("page.html") == content
