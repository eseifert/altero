"""A member and owner see policy changes and exercise real removal prompts."""

import httpx

from tools.compatibility.acceptance_runtime import AcceptanceRun


async def groups(run: AcceptanceRun) -> None:
    response = await run.request("POST", "/groups", json={"name": "Acceptance Group"})
    group_id = response.json()["id"]
    prefix = f"/groups/{group_id}"
    await run.request("POST", prefix + "/users", json={"userID": 2})

    async def phase(name, operations=(), **options):
        return await run.phase(
            name,
            operations,
            group_id=group_id,
            user_id=1 if name == "A" else 2,
            username="compatibility" if name == "A" else "compatibility2",
            key=run.server.keys[1 if name == "A" else 2],
            files=False,
            **options,
        )

    def permissions(snapshot, *, editable, files_editable, archived=False):
        group = next(value for value in snapshot["groups"] if value["id"] == group_id)
        assert group["editable"] is editable
        assert group["filesEditable"] is files_editable
        assert group["archived"] is archived

    await phase("A")
    permissions(await phase("B"), editable=True, files_editable=True)
    member = await phase("B", [dict(action="create", key="GRNP2345")])
    owner = await phase("A")
    await run.converged(member, owner, prefix)
    await run.request("PATCH", prefix, json={"libraryEditing": "admins", "fileEditing": "admins"})
    permissions(await phase("B"), editable=False, files_editable=False)
    permissions(await phase("A"), editable=True, files_editable=True)
    async with httpx.AsyncClient(base_url=run.server.url) as client:
        denied = await client.post(
            prefix + "/items",
            headers={"Zotero-API-Key": run.server.keys[2]},
            json=[dict(key="DENIED23", itemType="book")],
        )
    assert denied.status_code == 403, "Server still accepts writes by the restricted member"
    await run.request("PUT", prefix + "/users/2", json={"role": "admin"})
    permissions(await phase("B"), editable=True, files_editable=True)
    await run.request("PATCH", prefix, json={"fileEditing": "none"})
    permissions(await phase("B"), editable=True, files_editable=False)
    await run.request("PUT", prefix + "/users/2", json={"role": "member"})
    permissions(await phase("B"), editable=False, files_editable=False)
    await run.request("PATCH", prefix, json={"libraryEditing": "members", "fileEditing": "members"})
    await phase("B")
    await phase(
        "B",
        [dict(action="edit", key="GRNP2345", fields={"title": "Keep unsynced edit"})],
        sync=False,
    )
    await run.request("PATCH", prefix, json={"libraryEditing": "admins"})
    skipped = await phase(
        "B", dialogs=[dict(kind="prompt", text="Acceptance Group", button="Skip Group")]
    )
    assert skipped["items"][0]["title"] == "Keep unsynced edit"
    assert skipped["unsynced"]["item"], "Skipping discarded the member's pending change"
    reset = await phase(
        "B", dialogs=[dict(kind="prompt", text="Acceptance Group", button="Reset Group and Sync")]
    )
    assert reset["items"][0]["title"] == "Über 東京", "Reset did not restore server state"
    assert not reset["unsynced"]["item"]
    await run.request("PATCH", prefix, json={"libraryEditing": "members"})
    await phase("B")
    await phase("B", [dict(action="create", key="UNSYNCD2")], sync=False)
    await run.request("DELETE", prefix + "/users/2")
    kept = await phase(
        "B", dialogs=[dict(kind="prompt", text="Acceptance Group", button="Keep Group")]
    )
    permissions(kept, editable=False, files_editable=False, archived=True)
    assert {item["key"] for item in kept["items"]} == {"GRNP2345", "UNSYNCD2"}
    assert kept["unsynced"]["item"], "Keeping the group discarded unsynced local work"
    assert len(kept["dialogs"]) == 1
    assert {item["key"] for item in (await run.request("GET", prefix + "/items")).json()} == {
        "GRNP2345"
    }
    await run.request("POST", prefix + "/users", json={"userID": 2})
    returned = await phase("B")
    permissions(returned, editable=True, files_editable=True)
    await run.converged(returned, await phase("A"), prefix)
    await run.request("DELETE", prefix + "/users/2")
    removed = await phase(
        "B", dialogs=[dict(kind="prompt", text="Acceptance Group", button="Remove Group")]
    )
    assert removed["groups"] == [], "Removed group remains locally"
    assert removed["items"] == [], "Removed group's items remain locally"
    assert len(removed["dialogs"]) == 1
