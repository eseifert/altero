"""Link, revoke, relink and cancel switching accounts in actual desktops."""

import json

from tools.compatibility.acceptance_runtime import AcceptanceRun


async def credentials(run: AcceptanceRun) -> None:
    await run.phase("A", [dict(action="create", key="CREDS234")], files=False)
    initial = await run.phase("B", files=False)
    private = run.root / "B" / "login.json"

    async def link():
        await run.phase(
            "B", [dict(action="login-start", path=str(private))], files=False, sync=False
        )
        assert run.server.approve_login is not None
        await run.server.approve_login(json.loads(private.read_text())["sessionToken"])
        return await run.phase(
            "B", [dict(action="login-finish", path=str(private))], key=None, files=False
        )

    linked = await link()
    await run.converged(initial, linked)
    await run.phase("B", [dict(action="revoke-key")], key=None, sync=False, files=False)
    denied = await run.phase(
        "B",
        [dict(action="edit", key="CREDS234", fields=dict(title="Pending after revocation"))],
        key=None,
        files=False,
        expected_error="ERROR_API_KEY_INVALID",
    )
    assert denied["unsynced"]["item"], "Revoked sync lost pending local work"
    assert (await run.request("GET", "/users/1/items/CREDS234")).json()["data"][
        "title"
    ] == "Über 東京"
    relinked = await link()
    await run.converged(relinked, await run.phase("A", files=False))
    assert relinked["items"][0]["title"] == "Pending after revocation"
    refused = await run.phase(
        "B",
        key=run.server.keys[2],
        files=False,
        dialogs=[dict(kind="prompt", text="compatibility2", button="Cancel")],
    )
    assert refused["user_id"] == 1, "Account-switch cancellation changed the local owner"
    assert refused["items"] == relinked["items"], "Account-switch cancellation changed local items"
    assert not (await run.request("GET", "/users/2/items", key=run.server.keys[2])).json()
    await run.converged(await run.phase("B", files=False), await run.phase("A", files=False))
