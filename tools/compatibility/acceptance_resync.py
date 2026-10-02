"""Original personal-library reset paths and recovery from an older server archive."""

from altero.models import LibraryType
from altero.services import admin, transfer
from tools.compatibility.acceptance_runtime import AcceptanceRun


async def resync(run: AcceptanceRun) -> None:
    path = run.root / "restore.txt"
    path.write_text("Restored attachment bytes")
    first = await run.phase(
        "A",
        [
            dict(action="create", key="RESTNRE2"),
            dict(action="create", key="DELETE23"),
            dict(action="collection", key="RESETCL2", name="Original"),
            dict(action="file", key="RESTNRE2", collections=["RESETCL2"]),
            dict(action="attach", key="RESTNRE2", path=str(path)),
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
    await run.phase(
        "A",
        [
            dict(action="edit", key="RESTNRE2", fields={"title": "Discard pending edit"}),
            dict(action="create", key="LNCAL234"),
        ],
        sync=False,
    )
    remote = await run.phase(
        "B", [dict(action="edit", key="RESTNRE2", fields={"title": "Current remote"})]
    )
    reset = await run.phase("A", reset="from-server")
    await run.converged(reset, remote)
    assert all(item["key"] != "LNCAL234" for item in reset["items"])
    assert (
        next(item for item in reset["items"] if item["key"] == "RESTNRE2")["title"]
        == "Current remote"
    )
    await run.phase(
        "A",
        [
            dict(action="edit", key="RESTNRE2", fields={"title": "Authoritative local"}),
            dict(action="delete", key="DELETE23"),
        ],
        sync=False,
    )
    await run.phase("B", [dict(action="create", key="REMNTE23")])
    restored = await run.phase("A", reset="to-server")
    await run.converged(restored, await run.phase("B"))
    assert not {"DELETE23", "REMNTE23"} & {item["key"] for item in restored["items"]}
    assert (
        next(item for item in restored["items"] if item["key"] == "RESTNRE2")["title"]
        == "Authoritative local"
    )
    high = int(
        (await run.request("GET", "/users/1/items?format=versions")).headers[
            "Last-Modified-Version"
        ]
    )
    async with run.server.session_factory() as session:
        await transfer.import_library(
            session, archive=archive, storage_root=run.server.storage_path, replace=True
        )
        # Use the documented administrator recovery path: lift the restored watermark.
        await admin.set_library_version(
            session, library_type=LibraryType.USER, owner_id=1, version=high + 1
        )
    left, right = (
        await run.phase("A", reset="to-server"),
        await run.phase("B", reset="from-server"),
    )
    await run.converged(left, right)
    assert {item["key"] for item in left["items"]} == {item["key"] for item in restored["items"]}
    assert (
        next(item for item in left["items"] if item["key"] == "RESTNRE2")["title"]
        == "Authoritative local"
    )
    assert left["files"] == first["files"]
    await run.settled()
