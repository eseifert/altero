"""Real per-object permission failures preserve rejected work and settle successes."""

from tools.compatibility.acceptance_runtime import AcceptanceRun


async def partial_failures(run: AcceptanceRun) -> None:
    group_id = (await run.request("POST", "/groups", json={"name": "Partial results"})).json()["id"]
    prefix = f"/groups/{group_id}"
    await run.request("POST", prefix + "/users", json={"userID": 2})

    async def phase(name, operations=(), **options):
        user_id = 1 if name == "A" else 2
        return await run.phase(
            name,
            operations,
            group_id=group_id,
            user_id=user_id,
            username="compatibility" if user_id == 1 else "compatibility2",
            key=run.server.keys[user_id],
            files=False,
            **options,
        )

    await phase("A", [])
    await phase("B", [])
    await phase(
        "A",
        [
            dict(action="create", key="DENIED23"),
            dict(
                action="create",
                key="CHILD234",
                data=dict(itemType="note", parentItem="DENIED23", note="<p>owner</p>"),
            ),
        ],
    )
    await phase("B")
    await run.request("PUT", prefix + "/users/2", json={"permission": "own"})
    await phase("B")
    failed = await phase(
        "B",
        [
            dict(action="edit", key="DENIED23", fields={"title": "Pending parent"}),
            dict(action="json", key="CHILD234", data={"note": "<p>Pending child</p>"}),
            dict(action="create", key="SUCCESS2"),
        ],
        expected_upload_errors=[dict(code=403, key="DENIED23"), dict(code=403, key="CHILD234")],
    )
    assert len(failed["unsynced"]["item"]) == 2, (
        "Rejected objects were marked synced or success remained pending"
    )
    persisted = {item["key"]: item for item in (await run.request("GET", prefix + "/items")).json()}
    assert persisted["DENIED23"]["data"]["title"] == "Über 東京"
    assert persisted["CHILD234"]["data"]["note"] == "<p>owner</p>"
    assert "SUCCESS2" in persisted, "Mixed failure discarded the successful entry"
    # The original desktop retries its persisted queue after the cause is removed.
    await run.request("PUT", prefix + "/users/2", json={"permission": "inherit"})
    right, left = await phase("B"), await phase("A")
    await run.converged(left, right, prefix)
    state = {item["key"]: item for item in left["items"]}
    assert state["DENIED23"]["title"] == "Pending parent"
    assert state["CHILD234"]["note"] == "<p>Pending child</p>"
    watermark = (await run.request("GET", prefix + "/items?format=versions")).headers[
        "Last-Modified-Version"
    ]
    await run.converged(await phase("A"), await phase("B"), prefix)
    assert (await run.request("GET", prefix + "/items?format=versions")).headers[
        "Last-Modified-Version"
    ] == watermark
