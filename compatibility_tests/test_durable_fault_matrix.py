"""Each sync write family survives lost responses and an actual process restart."""

import hashlib

import httpx
import pytest
from sqlalchemy import update

from altero.models import Library
from tools.compatibility.process_server import process_server


@pytest.mark.parametrize(
    "family", ["collections", "searches", "settings", "deletions", "fulltext", "file-registration"]
)
@pytest.mark.parametrize("point", ["before", "response"])
async def test_durable_write_boundaries_and_retry_preconditions(tmp_path, family, point):
    await check_write_boundary(tmp_path, family, point)


async def check_write_boundary(tmp_path, family, point, *, corrupt_watermark=False):
    async with process_server(tmp_path / "server") as server:

        async def request(method, path, **options):
            async with httpx.AsyncClient(
                base_url=server.url, headers={"Zotero-API-Key": server.key}
            ) as client:
                return await client.request(method, path, **options)

        seeded = await request(
            "POST",
            "/users/1/items",
            json=[
                dict(
                    key="ATTACH23",
                    itemType="attachment",
                    linkMode="imported_file",
                    filename="research.txt",
                    contentType="text/plain",
                )
            ],
        )
        assert seeded.status_code == 200
        assert not seeded.json()["failed"]
        method = "POST"
        path = "/users/1/" + family
        options: dict = dict(headers={"If-Unmodified-Since-Version": "1"})
        if family == "collections":
            options["json"] = [dict(key="FAULT234", name="Durable collection")]
        elif family == "searches":
            options["json"] = [
                dict(
                    key="FAULT234",
                    name="Durable search",
                    conditions=[dict(condition="title", operator="contains", value="研究")],
                )
            ]
        elif family == "settings":
            options["json"] = dict(tagColors=dict(value=[dict(name="研究", color="#123456")]))
        elif family == "deletions":
            method, path = "DELETE", "/users/1/items?itemKey=ATTACH23"
        elif family == "fulltext":
            options["json"] = [
                dict(key="ATTACH23", content="研究 Unicode", indexedChars=10, totalChars=10)
            ]
        else:
            content = b"Durable file bytes"
            digest = hashlib.md5(content, usedforsecurity=False).hexdigest()
            path = "/users/1/items/ATTACH23/file"
            authorized = await request(
                "POST",
                path,
                headers={"If-None-Match": "*"},
                data=dict(
                    md5=digest,
                    filename="research.txt",
                    filesize=str(len(content)),
                    mtime="1785701798544",
                    contentType="text/plain",
                ),
            )
            assert authorized.status_code == 200
            permission = authorized.json()
            uploaded = await request("POST", permission["url"], content=content)
            assert uploaded.status_code < 300
            options = dict(
                headers={"If-None-Match": "*"}, data=dict(upload=permission["uploadKey"])
            )
        server.barrier.inject(method, path.split("?")[0], point, fault="status", status=503)
        failed = await request(method, path, **options)
        assert failed.status_code == 503
        assert server.barrier.reached.is_set()
        assert server.crash is not None
        assert server.restart is not None
        assert await server.crash() > 0
        await server.restart()
        if corrupt_watermark:
            assert server.session_factory is not None
            async with server.session_factory() as session:
                await session.execute(update(Library).values(version=1))
                await session.commit()
        committed = point == "response"
        versions = await request("GET", "/users/1/items?format=versions")
        assert versions.headers["Last-Modified-Version"] == ("2" if committed else "1")
        if family in {"collections", "searches"}:
            stored = await request("GET", "/users/1/" + family)
            assert bool(stored.json()) == committed
        elif family == "settings":
            stored = await request("GET", "/users/1/settings")
            assert bool(stored.json()) == committed
        elif family == "deletions":
            stored = await request("GET", "/users/1/deleted?since=0")
            assert stored.json()["items"] == (["ATTACH23"] if committed else [])
        elif family == "fulltext":
            stored = await request("GET", "/users/1/items/ATTACH23/fulltext")
            assert stored.status_code == (200 if committed else 404)
            if committed:
                assert stored.json()["content"] == "研究 Unicode"
        else:
            stored = (await request("GET", "/users/1/items/ATTACH23")).json()["data"]
            assert (stored.get("md5") == digest) == committed
        retry = await request(method, path, **options)
        if committed:
            # Registration consumes the upload token. A stale token is refused
            # before the file precondition; recovery discovers current metadata.
            assert retry.status_code == (404 if family == "file-registration" else 412)
        else:
            assert retry.status_code < 300
        assert (await request("GET", "/users/1/items?format=versions")).headers[
            "Last-Modified-Version"
        ] == "2"
        if family == "file-registration":
            downloaded = await request("GET", path, follow_redirects=True)
            assert downloaded.content == content


async def test_durable_fault_oracle_rejects_lost_committed_watermark_after_intact_baseline(
    tmp_path,
):
    await check_write_boundary(tmp_path / "baseline", "collections", "response")
    with pytest.raises(AssertionError):
        await check_write_boundary(
            tmp_path / "mutated", "collections", "response", corrupt_watermark=True
        )
