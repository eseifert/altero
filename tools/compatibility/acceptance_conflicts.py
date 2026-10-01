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
