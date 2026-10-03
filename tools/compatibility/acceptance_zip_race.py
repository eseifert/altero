"""Two original desktops upload different archives under the same file digest."""

import asyncio
import hashlib

from sqlalchemy import select

from altero.models import StorageUpload
from tools.compatibility.acceptance_runtime import AcceptanceRun


async def zipped_digest_race(run: AcceptanceRun) -> None:
    await run.phase("A", [dict(action="create", key="ZIPRACE2")])
    await run.phase("B")
    folder = run.root / "snapshot"
    folder.mkdir()
    path = folder / "index.html"
    content = (
        b'<!doctype html><html><head><link rel="stylesheet" href="style.css"></head>'
        b"<body>Same snapshot: research</body></html>"
    )
    path.write_bytes(content)
    (folder / "style.css").write_text("body { color: #123456; }")
    keys = []
    for index, name in enumerate(("A", "B")):
        created = await run.phase(
            name, [dict(action="snapshot", key="ZIPRACE2", path=str(path))], sync=False
        )
        key = next(iter(created["files"]))
        keys.append(key)
        await run.phase(
            name,
            [
                dict(
                    action="replace-file",
                    key=key,
                    path=str(path),
                    mtime=1785701798544 + index * 7200000,
                )
            ],
            sync=False,
        )
    barrier = run.server.barrier
    barrier.arm("POST", "/storage/upload/", "upload", prefix=True)
    first = asyncio.create_task(run.phase("A", timeout=180))
    second = None
    try:
        async with asyncio.timeout(90):
            await barrier.reached.wait()
            other = barrier.fork()
            other.arm("POST", "/storage/upload/", "response", prefix=True)
            second = asyncio.create_task(run.phase("B", timeout=180, expected_file_sync_error=True))
            await other.reached.wait()
            assert run.server.session_factory is not None
            async with run.server.session_factory() as session:
                uploads = list((await session.scalars(select(StorageUpload))).all())
                assert len(uploads) == 2, "Second upload reused the digest before bytes arrived"
                assert len({value.md5 for value in uploads}) == 1
                assert len({value.zip_md5 for value in uploads}) == 2, (
                    "Archives were identical; the race was ineffective"
                )
            barrier.release.set()
            await first
            other.release.set()
            await second
    finally:
        barrier.release_all()
        tasks = [task for task in (first, second) if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    left, right = await run.phase("A"), await run.phase("B")
    # B's recovery registers its attachment after A's preceding metadata read.
    left = await run.phase("A")
    await run.converged(left, right)
    expected = hashlib.md5(content, usedforsecurity=False).hexdigest()
    for snapshot in (left, right):
        for key in keys:
            item = next(item for item in snapshot["items"] if item["key"] == key)
            assert item["md5"] == expected
            assert snapshot["storage_states"][key] == "in_sync"
            assert snapshot["files"][key] == left["files"][keys[0]]
            assert snapshot["file_entries"][key] == left["file_entries"][keys[0]]
            assert "style.css" in snapshot["file_entries"][key], "Snapshot lost an auxiliary file"
    await run.settled()
