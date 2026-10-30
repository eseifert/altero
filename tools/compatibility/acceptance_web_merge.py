"""Browser merges propagate through two real desktop sync caches."""

import json

import httpx2

from tools.compatibility.acceptance_runtime import AcceptanceRun

MASTER = "MASTER23"
OTHER = "DUPL2345"
RELATED = "RELATED2"
NOTE = "CHILD234"
LINK = "ATTACH23"
COLLECTIONS = ("MCLE2345", "DCLE2345")
TITLE = "Engine notes, chosen in the browser"
CREATORS = [
    dict(creatorType="author", firstName="Luigi", lastName="Menabrea"),
    dict(creatorType="translator", firstName="Ada", lastName="Lovelace"),
]


def relation(item: dict, name: str) -> set[str]:
    values = item.get("relations", {}).get(name, [])
    return set(values if isinstance(values, list) else [values])


def uri(key: str) -> str:
    return f"http://zotero.org/users/1/items/{key}"


async def review_version(browser: httpx2.AsyncClient, keys: list[str]) -> int:
    response = await browser.get(
        "/items", params=dict(scope="all", itemKey=",".join(keys), limit=100)
    )
    response.raise_for_status()
    review = response.json()
    assert {item["key"] for item in review["items"]} == set(keys), "Review lost a selected item"
    return review["libraryVersion"]


async def merge_review(
    run: AcceptanceRun, browser: httpx2.AsyncClient, master: str, other: str, fields: dict
) -> dict:
    version = await review_version(browser, [master, other])
    body = dict(master=master, others=[other], fields=fields)
    response = await browser.post(
        "/items/merge",
        json=body,
        headers={"If-Unmodified-Since-Version": str(version)},
    )
    response.raise_for_status()
    changed = response.json()["items"]
    assert {item["version"] for item in changed} == {version + 1}, (
        "Browser merge did not use one new library version"
    )
    assert (await review_version(browser, [master])) == version + 1
    # Keep the exact review and result, without cookies or credentials.
    (run.root / f"browser-merge-{master}.json").write_text(
        json.dumps(dict(version=version, request=body, response=changed), indent=2) + "\n"
    )
    return {item["key"]: item["data"] for item in changed}


def assert_merged(snapshot: dict) -> None:
    state = {item["key"]: item for item in snapshot["items"]}
    master = state[MASTER]
    assert master["title"] == TITLE, "Desktop lost the browser's chosen title"
    assert master["creators"] == CREATORS, "Desktop lost the browser's chosen creators"
    assert master["dateAdded"] == "2020-01-01T00:00:00Z"
    assert set(master["collections"]) == set(COLLECTIONS), "Merge lost collection membership"
    assert {tag["tag"]: tag.get("type", 0) for tag in master["tags"]} == {
        "master": 0,
        "duplicate": 0,
        "shared": 0,
    }, "Merge lost tags or manual-tag precedence"
    assert state[OTHER].get("deleted"), "Desktop did not trash the duplicate"
    assert state[NOTE]["parentItem"] == state[LINK]["parentItem"] == MASTER, (
        "Desktop did not move the duplicate's children"
    )
    assert "A note to move" in state[NOTE]["note"]
    assert relation(master, "dc:relation") == {uri(RELATED)}
    assert relation(state[RELATED], "dc:relation") == {uri(MASTER)}, (
        "Incoming relation stayed stale"
    )
    assert relation(master, "dc:replaces") == {uri(OTHER), uri("PREV2345")}, (
        "Desktop merge history is missing"
    )
    assert not relation(state[OTHER], "dc:replaces"), "Old merge history was not transferred"


async def web_merge(run: AcceptanceRun) -> None:
    await run.phase(
        "A",
        [
            *(
                dict(action="collection", key=key, name=name)
                for key, name in zip(
                    COLLECTIONS, ("Master collection", "Duplicate collection"), strict=True
                )
            ),
            dict(
                action="create",
                key=MASTER,
                data=dict(
                    itemType="book",
                    title="Engine notes",
                    ISBN="9780262510875",
                    dateAdded="2020-01-01T00:00:00Z",
                    creators=[dict(creatorType="author", name="The master authors")],
                    tags=[dict(tag="master"), dict(tag="shared")],
                    collections=[COLLECTIONS[0]],
                ),
            ),
            dict(
                action="create",
                key=OTHER,
                data=dict(
                    itemType="book",
                    title="Duplicate engine notes",
                    ISBN="9780262510875",
                    dateAdded="2022-01-01T00:00:00Z",
                    tags=[dict(tag="duplicate"), dict(tag="shared", type=1)],
                    collections=[COLLECTIONS[1]],
                    relations={"dc:replaces": [uri("PREV2345")]},
                ),
            ),
            dict(action="create", key=RELATED, data=dict(itemType="book", title="Related work")),
            dict(action="related", key=OTHER, other=RELATED),
            dict(
                action="create",
                key=NOTE,
                data=dict(itemType="note", parentItem=OTHER, note="<p>A note to move</p>"),
            ),
            dict(
                action="create",
                key=LINK,
                data=dict(
                    itemType="attachment",
                    parentItem=OTHER,
                    linkMode="linked_url",
                    title="Online copy",
                    url="https://example.org/engine",
                    contentType="text/html",
                ),
            ),
        ],
        files=False,
    )
    await run.phase("B", files=False)

    async with run.browser() as browser:
        candidates = await browser.get("/items", params=dict(scope="duplicates", grouped=True))
        candidates.raise_for_status()
        assert [MASTER, OTHER] in candidates.json()["groups"], "Review group is incomplete"
        stale = await review_version(browser, [MASTER, OTHER])
        await run.phase(
            "B",
            [dict(action="edit", key=OTHER, fields=dict(extra="A desktop changed this first"))],
            files=False,
        )
        before = await review_version(browser, [MASTER, OTHER])
        refused = await browser.post(
            "/items/merge",
            json=dict(master=MASTER, others=[OTHER], fields=dict(title=TITLE)),
            headers={"If-Unmodified-Since-Version": str(stale)},
        )
        assert refused.status_code == 412, "A stale browser review overwrote a desktop change"
        assert await review_version(browser, [MASTER, OTHER]) == before
        assert (await browser.get(f"/items/{MASTER}")).json()["data"]["title"] == "Engine notes"
        changed = await merge_review(
            run, browser, MASTER, OTHER, dict(title=TITLE, creators=CREATORS)
        )
        assert set(changed) == {MASTER, OTHER, NOTE, LINK, RELATED}
        left, right = await run.phase("A", files=False), await run.phase("B", files=False)
        await run.converged(left, right)
        for snapshot in (left, right):
            assert_merged(snapshot)
    await run.settled(files=False)

    # Restoring recovers the duplicate record. It does not reverse the child moves.
    restored = await run.phase("B", [dict(action="restore", key=OTHER)], files=False)
    received = await run.phase("A", files=False)
    await run.converged(restored, received)
    for snapshot in (restored, received):
        state = {item["key"]: item for item in snapshot["items"]}
        assert not state[OTHER].get("deleted"), "The duplicate could not be restored"
        assert state[NOTE]["parentItem"] == state[LINK]["parentItem"] == MASTER
        assert state[MASTER]["title"] == TITLE
    await run.settled(files=False)
