"""A parent the server lost is uploaded again; a child moved out stays out."""

from altero.models import LibraryType
from altero.services import admin, transfer
from tools.compatibility.acceptance_runtime import AcceptanceRun


async def missing_parent(run: AcceptanceRun) -> None:
    """The desktop re-uploads a synced parent the server answers 409 for.

    Restoring an older archive takes away objects made after it without a
    deletion for any client to hear, so the desktop still holds the parent as
    synced. Its next child names a parent the server lacks; the 409 naming it
    in `data` is what makes `_checkObjectUploadError` queue the parent again.
    Answered without `data`, the child fails on every sync for good.
    """
    await run.phase("A", [dict(action="create", key="EARLIER2")], files=False)
    await run.phase("B", files=False)
    assert run.server.session_factory is not None
    assert run.server.storage_path is not None
    archive = run.root / "before-parent.zip"
    async with run.server.session_factory() as session:
        await transfer.export_library(
            session,
            library_type=LibraryType.USER,
            owner_id=1,
            storage_root=run.server.storage_path,
            destination=archive,
        )
    await run.phase("A", [dict(action="create", key="MISSPAR2")], files=False)
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
    stored = (await run.request("GET", "/users/1/items?format=keys")).text.split()
    assert "MISSPAR2" not in stored, "The restore did not take the parent away"

    await run.phase(
        "A",
        [
            dict(
                action="create",
                key="MISSCHL2",
                data=dict(itemType="note", parentItem="MISSPAR2", note="<p>Orphaned?</p>"),
            )
        ],
        files=False,
    )
    # A second sync, should the repair take one: the parent is queued while
    # the batch naming the child is answered.
    repaired = await run.phase("A", files=False)
    assert not repaired["unsynced"]["item"], "The desktop did not re-upload the lost parent"
    remote = {
        item["key"]: item["data"] for item in (await run.request("GET", "/users/1/items")).json()
    }
    assert "MISSPAR2" in remote, "The lost parent was not uploaded again"
    assert remote["MISSCHL2"]["parentItem"] == "MISSPAR2"
    await run.converged(repaired, await run.phase("B", files=False))
    await run.settled(files=False)


async def child_promotion(run: AcceptanceRun) -> None:
    """A note moved out to the library is top-level on the server and elsewhere.

    The desktop's patch says so with `parentItem: false`; read as absent, the
    note stayed a child on the server and on B while A believed it had synced.
    """
    await run.phase(
        "A",
        [
            dict(action="create", key="PRMTPAR2"),
            dict(
                action="create",
                key="PRMTNTE2",
                data=dict(itemType="note", parentItem="PRMTPAR2", note="<p>Moving out</p>"),
            ),
        ],
        files=False,
    )
    await run.phase("B", files=False)

    promoted = await run.phase(
        "A", [dict(action="json", key="PRMTNTE2", data=dict(parentItem=False))], files=False
    )
    remote = (await run.request("GET", "/users/1/items/PRMTNTE2")).json()["data"]
    assert "parentItem" not in remote, "The server kept the promoted note under its parent"
    other = await run.phase("B", files=False)
    note = next(item for item in other["items"] if item["key"] == "PRMTNTE2")
    assert not note.get("parentItem"), "The other desktop kept the note under its parent"
    await run.converged(promoted, other)
    await run.settled(files=False)
