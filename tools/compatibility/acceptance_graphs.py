"""Original desktop merge, publication and library-copy operations preserve graphs."""

from tools.compatibility.acceptance_runtime import AcceptanceRun


async def graphs(run: AcceptanceRun) -> None:
    group_id = (await run.request("POST", "/groups", json={"name": "Copy destination"})).json()[
        "id"
    ]
    await run.phase("A", all_libraries=True)
    await run.phase("B", all_libraries=True)
    path = run.root / "graph.txt"
    path.write_text("Graph attachment bytes")
    first = await run.phase(
        "A",
        [
            dict(action="create", key="MASTER23"),
            dict(action="create", key="DUPL2345"),
            dict(action="create", key="RELATED2"),
            dict(
                action="create",
                key="NNTE2345",
                data=dict(itemType="note", parentItem="DUPL2345", note="<p>Merge child</p>"),
            ),
            dict(action="attach", key="DUPL2345", path=str(path)),
            dict(action="related", key="DUPL2345", other="RELATED2"),
        ],
    )
    attachment = next(iter(first["files"]))
    await run.phase("B")
    merged = await run.phase("A", [dict(action="merge", key="MASTER23", others=["DUPL2345"])])
    downloaded = await run.phase("B")
    await run.converged(merged, downloaded)
    state = {item["key"]: item for item in downloaded["items"]}
    assert state["DUPL2345"]["deleted"]
    assert state["NNTE2345"]["parentItem"] == state[attachment]["parentItem"] == "MASTER23"
    assert state["MASTER23"]["relations"].get("dc:relation"), "Merge lost related-item links"
    published = await run.phase(
        "A",
        [
            dict(
                action="publish",
                key="MASTER23",
                options=dict(
                    childNotes=True,
                    childFileAttachments=True,
                    childLinks=True,
                    license="cc0",
                    licenseName="CC0",
                    keepRights=False,
                ),
            )
        ],
    )
    received = await run.phase("B")
    await run.converged(published, received)
    state = {item["key"]: item for item in received["items"]}
    assert all(state[key]["inPublications"] for key in ("MASTER23", "NNTE2345", attachment))
    assert state["MASTER23"]["rights"] == "CC0"
    copied = await run.phase(
        "A", [dict(action="copy-to-group", key="MASTER23", group_id=group_id)], all_libraries=True
    )
    assert {item["key"] for item in copied["items"]} == set(state), "Copy changed source keys"
    left, right = await run.phase("A", group_id=group_id), await run.phase("B", group_id=group_id)
    await run.converged(left, right, f"/groups/{group_id}")
    regular = next(item for item in right["items"] if item["itemType"] == "book")
    assert regular["key"] != "MASTER23"
    assert len(right["items"]) == 3, "Copy lost or duplicated graph children"
    assert all(
        item["parentItem"] == regular["key"]
        for item in right["items"]
        if item["itemType"] != "book"
    )
    assert list(right["files"].values()) == list(first["files"].values())
    # Repeat the same desktop copy: its linked-item relation must avoid a duplicate.
    await run.phase(
        "A", [dict(action="copy-to-group", key="MASTER23", group_id=group_id)], all_libraries=True
    )
    assert len((await run.phase("B", group_id=group_id))["items"]) == 3
    withdrawn = await run.phase("A", [dict(action="withdraw", key="MASTER23")])
    received = await run.phase("B")
    await run.converged(withdrawn, received)
    assert not any(item.get("inPublications") for item in received["items"])
    await run.settled()
