"""Select both sides of actual conflict dialogs and check settled sync state."""

from tools.compatibility.acceptance_runtime import AcceptanceRun

KEY = "CNFLICT2"


async def conflicts(run: AcceptanceRun) -> None:
    await run.phase("A", [dict(action="create", key=KEY)], files=False)
    await run.phase("B", files=False)
    for side in ("local", "remote"):
        local, remote = f"Chosen B {side}", f"Chosen A {side}"
        await run.phase("B", [dict(action="edit", key=KEY, fields={"title": local})], sync=False)
        await run.phase("A", [dict(action="edit", key=KEY, fields={"title": remote})], files=False)
        resolved = await run.phase(
            "B", files=False, dialogs=[dict(kind="merge", key=KEY, side=side)]
        )
        assert len(resolved["dialogs"]) == 1, "No actual conflict dialog was resolved"
        expected = local if side == "local" else remote
        assert resolved["items"][0]["title"] == expected, "Dialog selection was not applied"
        settled = await run.phase("A", files=False)
        await run.converged(resolved, settled)
        version = (await run.request("GET", "/users/1/items?format=versions")).headers[
            "Last-Modified-Version"
        ]
        await run.converged(settled, await run.phase("B", files=False))
        assert (await run.request("GET", "/users/1/items?format=versions")).headers[
            "Last-Modified-Version"
        ] == version, "Resolved conflict keeps uploading"
    await run.phase(
        "B",
        [dict(action="edit", key=KEY, fields=dict(title="Edited before deletion"))],
        sync=False,
        files=False,
    )
    await run.phase("A", [dict(action="delete", key=KEY)], files=False)
    # Keeping an edit leaves its old object version in this desktop. A 404
    # triggers full sync and another deletion prompt; Cancel preserves the edit.
    retained = await run.phase(
        "B",
        files=False,
        dialogs=[
            dict(kind="merge", key=KEY, side="local"),
            dict(kind="merge", key=KEY, side="cancel"),
        ],
    )
    assert retained["items"][0]["title"] == "Edited before deletion"
    assert retained["unsynced"]["item"], "Cancelling the repeated prompt lost the edit"
    recreated = await run.phase(
        "B", files=False, dialogs=[dict(kind="merge", key=KEY, side="local")]
    )
    assert recreated["items"][0]["title"] == "Edited before deletion"
    await run.converged(recreated, await run.phase("A", files=False))
    await run.phase(
        "B",
        [dict(action="edit", key=KEY, fields=dict(title="Edited again before deletion"))],
        sync=False,
        files=False,
    )
    await run.phase("A", [dict(action="delete", key=KEY)], files=False)
    resolved = await run.phase(
        "B", files=False, dialogs=[dict(kind="merge", key=KEY, side="remote")]
    )
    assert not resolved["items"], "Choosing the remote deletion retained the item"
    await run.converged(resolved, await run.phase("A", files=False))


async def filing(run: AcceptanceRun) -> None:
    """Merge independent tags and membership additions without a dialog."""
    await run.phase(
        "A",
        [
            dict(action="create", key="TAGKEY23"),
            dict(action="collection", key="CLLA2345", name="Alpha"),
            dict(action="collection", key="CLLB2345", name="Beta"),
        ],
        files=False,
    )
    await run.phase("B", files=False)
    for name, tag, collection in (("A", "Alpha", "CLLA2345"), ("B", "Beta", "CLLB2345")):
        await run.phase(
            name,
            [
                dict(
                    action="json",
                    key="TAGKEY23",
                    data=dict(tags=[dict(tag=tag)], collections=[collection]),
                )
            ],
            sync=False,
            files=False,
        )
    await run.phase("A", files=False)
    merged = await run.phase("B", files=False)
    await run.converged(merged, await run.phase("A", files=False))
    item = next(item for item in merged["items"] if item["key"] == "TAGKEY23")
    assert {tag["tag"] for tag in item["tags"]} == {"Alpha", "Beta"}
    assert set(item["collections"]) == {"CLLA2345", "CLLB2345"}
