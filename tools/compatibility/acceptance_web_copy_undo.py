"""Copy undo reaches both group caches and keeps originals and registered files."""

from sqlalchemy import select

from altero.models import Library, LibraryType
from tools.compatibility.acceptance_runtime import AcceptanceRun

ORIGINAL = "CPYUND23"
NOTE = "CPYNT234"


async def web_copy_undo(run: AcceptanceRun) -> None:
    group_id = (await run.request("POST", "/groups", json={"name": "Copy undo target"})).json()[
        "id"
    ]
    assert run.server.session_factory is not None
    async with run.server.session_factory() as session:
        target = await session.scalar(
            select(Library).where(
                Library.type == LibraryType.GROUP,
                Library.owner_id == group_id,
            )
        )
        assert target is not None
        target_id = target.id
    path = run.root / "copied.txt"
    path.write_bytes(b"Bytes retained through copy, undo and restore")
    original = await run.phase(
        "A",
        [
            dict(
                action="create",
                key=ORIGINAL,
                data=dict(itemType="book", title="Copy undo original"),
            ),
            dict(
                action="create",
                key=NOTE,
                data=dict(
                    itemType="note",
                    parentItem=ORIGINAL,
                    note="<p>Keep this copied note</p>",
                ),
            ),
            dict(action="attach", key=ORIGINAL, path=str(path)),
        ],
        all_libraries=True,
    )
    received = await run.phase("B", all_libraries=True)
    await run.converged(original, received)
    source_keys = {item["key"] for item in original["items"]}
    assert len(source_keys) == 3
    assert len(original["files"]) == 1
    file_bytes = list(original["files"].values())

    async def destination() -> dict:
        left = await run.phase("A", group_id=group_id)
        right = await run.phase("B", group_id=group_id)
        await run.converged(left, right, f"/groups/{group_id}")
        assert list(right["files"].values()) == file_bytes, "Copy undo lost registered bytes"
        return {item["key"]: item for item in right["items"]}

    async with run.browser() as browser:
        copied = await browser.post("/items/copy", json=dict(items=[ORIGINAL], library=target_id))
        copied.raise_for_status()
        root = copied.json()["items"][0]["key"]
        snapshot = copied.json()["undo"]
        assert root not in source_keys
        assert snapshot["items"] == [dict(key=root, deleted=True)]
        items = await destination()
        assert len(items) == 3
        assert all(item.get("parentItem") == root for key, item in items.items() if key != root)
        note_key = next(key for key, item in items.items() if item["itemType"] == "note")
        assert items[note_key]["note"] == "<p>Keep this copied note</p>"

        undone = await browser.post(
            f"{run.server.url}/web/libraries/{target_id}/items/undo",
            json=dict(items=snapshot["items"]),
            headers={"If-Unmodified-Since-Version": str(snapshot["version"])},
        )
        undone.raise_for_status()
        assert int(undone.headers["Last-Modified-Version"]) == snapshot["version"] + 1
        items = await destination()
        assert items[root]["deleted"], "Copy undo did not reach both desktops"
        assert items[note_key]["parentItem"] == root

        restored = await browser.patch(
            f"{run.server.url}/web/libraries/{target_id}/items",
            json=dict(items=[root], deleted=False),
        )
        restored.raise_for_status()
        items = await destination()
        assert not items[root].get("deleted")
        assert items[note_key]["note"] == "<p>Keep this copied note</p>"
        assert items[note_key]["parentItem"] == root

    left, right = await run.phase("A"), await run.phase("B")
    await run.converged(left, right)
    assert {item["key"] for item in right["items"]} == source_keys
    assert not any(item.get("deleted") for item in right["items"]), "Undo touched the source"
    assert list(right["files"].values()) == file_bytes
    await run.settled(prefix=f"/groups/{group_id}", group_id=group_id)
    await run.settled()
