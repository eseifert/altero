"""Prove the limits of archive rewind and recover from an authoritative desktop."""

from altero.models import LibraryType
from altero.services import admin, transfer
from tools.compatibility.acceptance_runtime import AcceptanceRun


async def backup_rewind(run: AcceptanceRun) -> None:
    path = run.root / "backup.txt"
    path.write_text("Original bytes")
    old = await run.phase(
        "A",
        [
            dict(action="create", key="BACKUP23"),
            dict(action="attach", key="BACKUP23", path=str(path)),
        ],
    )
    await run.phase("B")
    assert run.server.session_factory is not None
    assert run.server.storage_path is not None
    archive = run.root / "older.zip"
    async with run.server.session_factory() as session:
        await transfer.export_library(
            session,
            library_type=LibraryType.USER,
            owner_id=1,
            storage_root=run.server.storage_path,
            destination=archive,
        )
    current = await run.phase(
        "A",
        [
            dict(action="edit", key="BACKUP23", fields={"title": "Already synced current"}),
            dict(action="create", key="AFTER234"),
        ],
    )
    await run.converged(current, await run.phase("B"))
    high = int(
        (await run.request("GET", "/users/1/items?format=versions")).headers[
            "Last-Modified-Version"
        ]
    )
    async with run.server.session_factory() as session:
        await transfer.import_library(
            session, archive=archive, storage_root=run.server.storage_path, replace=True
        )
        await admin.set_library_version(
            session, library_type=LibraryType.USER, owner_id=1, version=high + 1
        )
    # An increased watermark alone cannot make older object versions overwrite
    # newer synchronized desktop caches, nor communicate vanished new objects.
    for name in ("A", "B"):
        observed = await run.phase(name)
        item = next(item for item in observed["items"] if item["key"] == "BACKUP23")
        assert item["title"] == "Already synced current", (
            "Desktop behavior changed: review rewind recovery"
        )
        assert any(item["key"] == "AFTER234" for item in observed["items"])
        assert not observed["unsynced"]["item"]
    remote = (await run.request("GET", "/users/1/items/BACKUP23")).json()["data"]
    assert (
        remote["title"] == next(item for item in old["items"] if item["key"] == "BACKUP23")["title"]
    )
    assert not any(
        item["key"] == "AFTER234" for item in (await run.request("GET", "/users/1/items")).json()
    )
    # Choose the surviving desktop as authoritative using the original reset.
    left = await run.phase("A", reset="to-server")
    right = await run.phase("B", reset="from-server")
    await run.converged(left, right)
    assert left["files"] == old["files"]
    assert {item["key"] for item in left["items"]} == {item["key"] for item in current["items"]}
    await run.settled()
