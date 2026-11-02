"""A browser undo is a new sync write; it must preserve unrelated stored state."""

from tools.compatibility.acceptance_runtime import AcceptanceRun

FIRST = "UND23456"
SECOND = "UND23457"
TRASHED = "UND23458"
NOTE = "UNDN2345"
ORIGINAL = "UNDC2345"
TARGET = "UNDC2346"
KEEP = "UNDC2347"


async def web_undo(run: AcceptanceRun) -> None:
    await run.phase(
        "A",
        [
            dict(action="collection", key=ORIGINAL, name="Original"),
            dict(action="collection", key=TARGET, name="Target"),
            dict(action="collection", key=KEEP, name="Keep"),
            dict(
                action="create",
                key=FIRST,
                data=dict(
                    itemType="book",
                    title="Undo first",
                    collections=[ORIGINAL, KEEP],
                ),
            ),
            dict(
                action="create",
                key=SECOND,
                data=dict(
                    itemType="book",
                    title="Already filed",
                    collections=[TARGET],
                ),
            ),
            dict(
                action="create",
                key=TRASHED,
                data=dict(
                    itemType="book",
                    title="Already trashed",
                    deleted=True,
                ),
            ),
            dict(
                action="create",
                key=NOTE,
                data=dict(
                    itemType="note",
                    parentItem=FIRST,
                    note="<p>Keep this child note</p>",
                ),
            ),
        ],
        files=False,
    )
    await run.phase("B", files=False)

    async def persisted() -> dict[str, dict]:
        left = await run.phase("A", files=False)
        right = await run.phase("B", files=False)
        await run.converged(left, right)
        return {item["key"]: item for item in right["items"]}

    async with run.browser() as browser:

        async def reverse(snapshot: dict) -> None:
            response = await browser.post(
                "/items/undo",
                json=dict(items=snapshot["items"]),
                headers={"If-Unmodified-Since-Version": str(snapshot["version"])},
            )
            response.raise_for_status()
            assert int(response.headers["Last-Modified-Version"]) == snapshot["version"] + 1

        trashed = await browser.patch("/items", json=dict(items=[FIRST, TRASHED], deleted=True))
        trashed.raise_for_status()
        snapshot = trashed.json()["undo"]
        assert snapshot["items"] == [dict(key=FIRST, deleted=False)]
        items = await persisted()
        assert items[FIRST]["deleted"]
        assert items[TRASHED]["deleted"]
        await reverse(snapshot)
        items = await persisted()
        assert not items[FIRST].get("deleted"), "Undo did not restore the trashed item"
        assert items[TRASHED]["deleted"], "Undo restored an item already in the trash"
        assert items[NOTE]["parentItem"] == FIRST
        assert items[NOTE]["note"] == "<p>Keep this child note</p>"

        filed = await browser.patch(
            "/items",
            json=dict(
                items=[FIRST, SECOND],
                addCollections=[TARGET],
                removeCollections=[ORIGINAL],
            ),
        )
        filed.raise_for_status()
        snapshot = filed.json()["undo"]
        assert snapshot["items"] == [dict(key=FIRST, collections=sorted([ORIGINAL, KEEP]))]
        items = await persisted()
        assert sorted(items[FIRST]["collections"]) == sorted([KEEP, TARGET])
        assert items[SECOND]["collections"] == [TARGET]
        await reverse(snapshot)
        items = await persisted()
        assert sorted(items[FIRST]["collections"]) == sorted([ORIGINAL, KEEP])
        assert items[SECOND]["collections"] == [TARGET], "Undo removed a prior membership"

        trashed = await browser.patch("/items", json=dict(items=[FIRST], deleted=True))
        trashed.raise_for_status()
        snapshot = trashed.json()["undo"]
        await run.phase(
            "B",
            [
                dict(
                    action="edit",
                    key=SECOND,
                    fields=dict(title="Desktop changed this library"),
                )
            ],
            files=False,
        )
        refused = await browser.post(
            "/items/undo",
            json=dict(items=snapshot["items"]),
            headers={"If-Unmodified-Since-Version": str(snapshot["version"])},
        )
        assert refused.status_code == 412, refused.text
        items = await persisted()
        assert items[FIRST]["deleted"], "Stale undo changed the library"
        assert items[SECOND]["title"] == "Desktop changed this library"
    await run.settled(files=False)
