"""Undo a fully synced merge, including PDF notes and annotation parents."""

from tools.compatibility.acceptance_runtime import AcceptanceRun
from tools.compatibility.acceptance_web_merge import relation, review_version, uri
from tools.compatibility.acceptance_web_merge_files import TEXT, pdf

MASTER, OTHER, NOTE, RELATED = "MRGMAS23", "MRGDUP23", "MRGNTE23", "MRGREL23"
ANNOTATION = "MRGANN23"
COLLECTIONS = ("MRGCLE23", "MRGCLE24")


def content(item: dict) -> dict:
    """Versions and modification times advance; the old content must return."""
    result = {key: value for key, value in item.items() if key not in {"version", "dateModified"}}
    result["tags"] = sorted(result.get("tags", []), key=lambda tag: tag["tag"])
    result["collections"] = sorted(result.get("collections", []))
    result["relations"] = {
        predicate: sorted(values if isinstance(values, list) else [values])
        for predicate, values in result.get("relations", {}).items()
    }
    return result


async def web_merge_undo(run: AcceptanceRun) -> None:
    await run.phase(
        "A",
        [
            *(dict(action="collection", key=key, name=key) for key in COLLECTIONS),
            *(
                dict(
                    action="create",
                    key=key,
                    data=dict(
                        itemType="book",
                        title=title,
                        dateAdded=f"{year}-01-01T00:00:00Z",
                        creators=[dict(creatorType="author", name=title)],
                        collections=[collection],
                        tags=[dict(tag=title)],
                    ),
                )
                for key, title, year, collection in (
                    (MASTER, "Merge undo original", 2022, COLLECTIONS[0]),
                    (OTHER, "Merge undo duplicate", 2020, COLLECTIONS[1]),
                )
            ),
            dict(action="create", key=RELATED, data=dict(itemType="book", title="Incoming link")),
            dict(action="related", key=OTHER, other=RELATED),
            dict(
                action="create",
                key=NOTE,
                data=dict(
                    itemType="note",
                    parentItem=OTHER,
                    note=f"<p>%2Fitems%2F{OTHER}</p>",
                ),
            ),
        ],
    )
    async with run.browser() as browser:
        files = []
        body = pdf(TEXT, False)
        for parent in (MASTER, OTHER):
            response = await browser.post(
                "/attachments",
                params=dict(parentItem=parent, filename=f"{parent}.pdf"),
                content=body,
                headers={"Content-Type": "application/pdf"},
            )
            response.raise_for_status()
            files.append(response.json()["key"])
        # Ensure the restored duplicate is processed before the survivor. Its
        # undelete removes dc:replaces locally, making the survivor's incoming
        # relation-only change redundant. Random keys otherwise hide that path.
        files.sort(reverse=True)
        reassigned = await run.request(
            "POST",
            "/users/1/items",
            json=[
                dict(
                    key=key,
                    version=(await browser.get(f"/items/{key}")).json()["version"],
                    parentItem=parent,
                )
                for key, parent in zip(files, (MASTER, OTHER), strict=True)
            ],
        )
        assert not reassigned.json()["failed"]
        await run.phase("A")
        await run.phase("B")
        original = await run.phase(
            "A",
            [
                *(
                    dict(action="json", key=key, data=dict(note=f"<p>Embedded {key}</p>"))
                    for key in files
                ),
                dict(
                    action="create",
                    key=ANNOTATION,
                    data=dict(
                        itemType="annotation",
                        parentItem=files[1],
                        annotationType="highlight",
                        annotationText="Return to the original PDF",
                        annotationColor="#ffd400",
                        annotationSortIndex="00000|000001|00000",
                        annotationPageLabel="1",
                        annotationPosition='{"pageIndex":0,"rects":[[20,20,80,40]]}',
                    ),
                ),
            ],
        )
        await run.converged(original, await run.phase("B"))
        before = {item["key"]: content(item) for item in original["items"]}
        version = await review_version(browser, [MASTER, OTHER])
        merged = await browser.post(
            "/items/merge",
            json=dict(
                master=MASTER,
                others=[OTHER],
                fields=dict(
                    title="Chosen in browser",
                    creators=[],
                    extra="Added by merge",
                ),
            ),
            headers={"If-Unmodified-Since-Version": str(version)},
        )
        merged.raise_for_status()
        snapshot = merged.json()["undo"]
        generated = {item["key"] for item in merged.json()["items"]} - before.keys()
        assert len(generated) == 1, "Merge did not promote the second embedded note"
        left, right = await run.phase("A"), await run.phase("B")
        await run.converged(left, right)
        for state in (left, right):
            values = {item["key"]: item for item in state["items"]}
            assert values[MASTER]["title"] == "Chosen in browser"
            assert values[OTHER].get("deleted")
            assert values[NOTE]["parentItem"] == MASTER
            assert values[ANNOTATION]["parentItem"] == files[0]
            assert relation(values[MASTER], "dc:replaces") == {uri(OTHER)}

        undone = await browser.post(
            "/items/merge/undo",
            headers={"If-Unmodified-Since-Version": str(snapshot["version"])},
        )
        undone.raise_for_status()
        assert int(undone.headers["Last-Modified-Version"]) == snapshot["version"] + 1
        left, right = await run.phase("A"), await run.phase("B")
        await run.converged(left, right)
        for state in (left, right):
            values = {item["key"]: item for item in state["items"]}
            for key, previous in before.items():
                assert content(values[key]) == previous, f"Merge undo lost original content: {key}"
            assert all(values[key].get("deleted") for key in generated), (
                "Promoted notes stayed active"
            )
            assert state["files"] == original["files"], "Merge undo changed PDF bytes"
            assert all(state["storage_states"][key] == "in_sync" for key in files)
        for key in files:
            response = await browser.get(f"/items/{key}/file")
            response.raise_for_status()
            assert response.content == body
        assert (
            await browser.post(
                "/items/merge/undo",
                headers={"If-Unmodified-Since-Version": str(snapshot["version"])},
            )
        ).status_code == 412
    await run.settled()
