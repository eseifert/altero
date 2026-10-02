"""Changes to object graphs travel through real sync caches on both desktops."""

from tools.compatibility.acceptance_runtime import AcceptanceRun


async def relationships(run: AcceptanceRun) -> None:
    await run.phase(
        "A",
        [
            dict(action="create", key="PARENT23"),
            dict(action="create", key="NTHER234"),
            dict(action="collection", key="BASE2345", name="Root"),
            dict(action="collection", key="BRANCH23", name="Branch", parent="BASE2345"),
            dict(action="collection", key="LEAF2345", name="Leaf", parent="BRANCH23"),
            dict(action="file", key="PARENT23", collections=["LEAF2345"]),
            dict(
                action="create",
                key="CHILD234",
                data={"itemType": "note", "parentItem": "PARENT23", "note": "<p>Child</p>"},
            ),
            dict(
                action="create",
                key="ATTACH23",
                data=dict(
                    itemType="attachment",
                    parentItem="PARENT23",
                    linkMode="imported_file",
                    title="PDF",
                    filename="research.pdf",
                    contentType="application/pdf",
                ),
            ),
            dict(
                action="create",
                key="ANN23456",
                data=dict(
                    itemType="annotation",
                    parentItem="ATTACH23",
                    annotationType="highlight",
                    annotationText="東京",
                    annotationComment="Über",
                    annotationColor="#ffd400",
                    annotationPageLabel="1",
                    annotationSortIndex="00000|000001|00000",
                    annotationPosition='{"pageIndex":0,"rects":[[1,2,3,4]]}',
                ),
            ),
            dict(
                action="search",
                key="SEARCH23",
                name="Research",
                conditions=[dict(condition="title", operator="contains", value="Über")],
            ),
        ],
        files=False,
    )
    await run.phase("B", files=False)
    changed = await run.phase(
        "B",
        [
            dict(action="collection", key="BRANCH23", name="Moved", parent=False),
            dict(action="json", key="CHILD234", data={"parentItem": "NTHER234"}),
            dict(action="json", key="ATTACH23", data={"parentItem": "NTHER234"}),
            dict(
                action="json",
                key="ANN23456",
                data=dict(
                    annotationComment="Changed 東京",
                    annotationColor="#ff6666",
                    annotationPosition='{"pageIndex":0,"rects":[[5,6,7,8]]}',
                ),
            ),
            dict(
                action="json",
                key="PARENT23",
                data={
                    "itemType": "journalArticle",
                    "publicationTitle": "研究",
                    "tags": [{"tag": "Changed"}],
                },
            ),
            dict(
                action="search",
                key="SEARCH23",
                name="Changed query",
                conditions=[dict(condition="tag", operator="is", value="Changed")],
            ),
        ],
        files=False,
    )
    received = await run.phase("A", files=False)
    await run.converged(changed, received)
    items = {item["key"]: item for item in received["items"]}
    collections = {item["key"]: item for item in received["collections"]}
    assert items["CHILD234"]["parentItem"] == "NTHER234"
    assert items["ATTACH23"]["parentItem"] == "NTHER234"
    assert items["ANN23456"]["parentItem"] == "ATTACH23"
    assert items["ANN23456"]["annotationComment"] == "Changed 東京"
    assert items["PARENT23"]["itemType"] == "journalArticle"
    assert items["PARENT23"]["collections"] == ["LEAF2345"]
    assert collections["BRANCH23"]["parentCollection"] is False
    assert collections["LEAF2345"]["parentCollection"] == "BRANCH23"
    assert received["searches"][0]["conditions"] == [
        dict(condition="tag", operator="is", value="Changed")
    ]
    cleared = await run.phase(
        "A",
        [dict(action="json", key="PARENT23", data={"tags": [], "collections": []})],
        files=False,
    )
    await run.converged(cleared, await run.phase("B", files=False))
