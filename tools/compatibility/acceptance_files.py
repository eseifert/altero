"""Replace persisted bytes, resolve competing files, and recover a missing copy."""

import asyncio
import base64
import hashlib
import time

import httpx

from tools.compatibility.acceptance_runtime import AcceptanceRun


async def files(run: AcceptanceRun) -> None:
    original = b"%PDF-1.4\nOriginal disposable bytes\n%%EOF\n"
    path = run.root / "research.pdf"
    path.write_bytes(original)
    await run.phase(
        "A",
        [
            dict(action="create", key="FILEP234"),
            dict(action="attach", key="FILEP234", path=str(path.resolve())),
        ],
    )
    first = await run.phase("B")
    key = next(iter(first["files"]))
    assert first["files"][key] == base64.b64encode(original).decode()
    mtime = time.time_ns() // 1_000_000 + 30_000

    async def replace(name, content, offset, *, sync):
        source = run.root / f"replacement-{name}-{offset}.pdf"
        source.write_bytes(content)
        return await run.phase(
            name,
            [
                dict(
                    action="replace-file", key=key, path=str(source.resolve()), mtime=mtime + offset
                )
            ],
            sync=sync,
        )

    async def verify(left, right, expected):
        await run.converged(left, right)
        assert left["files"][key] == base64.b64encode(expected).decode()
        response = await run.request("GET", f"/users/1/items/{key}")
        assert response.json()["data"]["md5"] == hashlib.md5(expected).hexdigest()
        async with httpx.AsyncClient(base_url=run.server.url, follow_redirects=True) as client:
            downloaded = await client.get(
                f"/users/1/items/{key}/file", headers={"Zotero-API-Key": run.server.key}
            )
            downloaded.raise_for_status()
            assert downloaded.content == expected, "Server persisted different attachment bytes"

    changed = b"%PDF-1.4\nReplacement from A\n%%EOF\n"
    await verify(await replace("A", changed, 1000, sync=True), await run.phase("B"), changed)
    for index, side in enumerate(("local", "remote"), start=1):
        local = f"%PDF-1.4\nB {side}\n%%EOF\n".encode()
        remote = f"%PDF-1.4\nA {side}\n%%EOF\n".encode()
        await replace("A", remote, index * 10000, sync=False)
        # Zotero tolerates a one-hour clock offset during the metadata scan.
        # This preserves both files until ZFS compares their hashes, while the
        # distinct displayed dates let its dialog distinguish the chosen side.
        offline = await replace("B", local, index * 10000 + 3_600_000, sync=False)
        assert offline["storage_states"][key] == "to_upload", "Offline file change was not detected"
        barrier = run.server.barrier
        barrier.arm("POST", f"/users/1/items/{key}/file")
        pending = asyncio.create_task(
            run.phase("B", dialogs=[dict(kind="merge", key=key, side=side)])
        )
        try:
            async with asyncio.timeout(60):
                await barrier.reached.wait()
            await run.phase("A")
        except BaseException:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            raise
        finally:
            barrier.release.set()
        resolved = await pending
        assert resolved["dialogs"][0]["type"] == "file", "Expected the file conflict dialog"
        # The tolerated clock offset also suppresses A's automatic download. Removing
        # the stale local copy asks the real scanner to recover it from storage.
        settled = await run.phase(
            "A",
            [dict(action="remove-file", key=key), dict(action="download-file", key=key)]
            if side == "local"
            else [],
        )
        await verify(resolved, settled, local if side == "local" else remote)
    missing = await run.phase("B", [dict(action="remove-file", key=key)])
    assert missing["files"][key] is None
    assert missing["storage_states"][key] == "to_download"
    recovered = await run.phase("B", [dict(action="download-file", key=key)])
    await verify(recovered, await run.phase("A"), remote)
    for snapshot in (recovered, await run.phase("B")):
        assert snapshot["storage_states"][key] == "in_sync", "File transfer is still pending"
    directory = run.root / "snapshot"
    directory.mkdir()
    html, css = (
        b'<html><link rel="stylesheet" href="paper.css"><p>Snapshot</p></html>',
        b"p {color: navy}",
    )
    (directory / "index.html").write_bytes(html)
    (directory / "paper.css").write_bytes(css)
    imported = await run.phase(
        "A",
        [dict(action="snapshot", key="FILEP234", path=str((directory / "index.html").resolve()))],
    )
    unpacked = await run.phase("B")
    await run.converged(imported, unpacked)
    snapshot_key = next(
        item["key"] for item in unpacked["items"] if item.get("linkMode") == "imported_url"
    )
    assert imported["file_entries"][snapshot_key] == unpacked["file_entries"][snapshot_key]
    assert unpacked["file_entries"][snapshot_key] == {
        "index.html": base64.b64encode(html).decode(),
        "paper.css": base64.b64encode(css).decode(),
    }, "Snapshot resources were not unpacked to disk"
