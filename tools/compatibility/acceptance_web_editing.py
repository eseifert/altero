"""Items edited in the browser reach both desktops, and a desktop's edit wins a race."""

import httpx2
from sqlalchemy import select

from altero.models import Library, User
from altero.services import websessions
from tools.compatibility.acceptance_runtime import AcceptanceRun

EDITED = "WEBEDIT2"
RELATED = "WEBREL23"


def related_to(item: dict) -> list[str]:
    """The items ``item`` names in `dc:relation`, one or several as JSON writes them."""
    named = (item.get("relations") or {}).get("dc:relation", [])
    return named if isinstance(named, list) else [named]


async def web_editing(run: AcceptanceRun) -> None:
    """Every write the item pane makes, read back by the desktop's own sync.

    Fields, creators and tags in one edit; a related-items link, which writes
    both items; a type change; and an item made in the browser and then named.
    Afterwards a desktop changes the same item, and the browser's edit stating
    the version it had read is refused rather than written over it.
    """
    await run.phase(
        "A",
        [
            dict(
                action="create",
                key=EDITED,
                data=dict(
                    itemType="book",
                    title="Sketch of the Analytical Engine",
                    creators=[dict(creatorType="author", firstName="Luigi", lastName="Menabrea")],
                    tags=[dict(tag="engine")],
                ),
            ),
            dict(action="create", key=RELATED, data=dict(itemType="book", title="Notes")),
        ],
        files=False,
    )
    await run.phase("B", files=False)

    assert run.server.session_factory is not None
    async with run.server.session_factory() as session:
        user = await session.get(User, 1)
        assert user is not None
        token, _ = await websessions.create(session, user)
        library = await session.scalar(select(Library).where(Library.owner_id == 1))
        assert library is not None
        library_id = library.id

    async with httpx2.AsyncClient(
        base_url=f"{run.server.url}/web/libraries/{library_id}",
        cookies={"altero_session": token, "altero_csrf": "acceptance-csrf"},
        headers={"X-CSRF-Token": "acceptance-csrf"},
    ) as browser:

        async def version(key: str) -> int:
            read = await browser.get(f"/items/{key}")
            read.raise_for_status()
            return read.json()["version"]

        edited = await browser.patch(
            f"/items/{EDITED}",
            json=dict(
                version=await version(EDITED),
                fields=dict(title="Sketch of the Analytical Engine, translated", date="1843"),
                creators=[
                    dict(creatorType="author", firstName="Luigi", lastName="Menabrea"),
                    dict(creatorType="translator", firstName="Ada", lastName="Lovelace"),
                ],
                tags=[dict(tag="engine"), dict(tag="translation")],
            ),
        )
        edited.raise_for_status()
        related = await browser.post(f"/items/{EDITED}/related", json=dict(items=[RELATED]))
        related.raise_for_status()
        retyped = await browser.patch(
            f"/items/{RELATED}", json=dict(version=await version(RELATED), itemType="report")
        )
        retyped.raise_for_status()
        created = await browser.post("/items", json=dict(itemType="journalArticle"))
        created.raise_for_status()
        made = created.json()["key"]
        named = await browser.patch(
            f"/items/{made}",
            json=dict(version=created.json()["version"], fields=dict(title="Made in a browser")),
        )
        named.raise_for_status()

        left, right = await run.phase("A", files=False), await run.phase("B", files=False)
        await run.converged(left, right)
        items = {item["key"]: item for item in right["items"]}
        assert items[EDITED]["title"] == "Sketch of the Analytical Engine, translated"
        assert items[EDITED]["date"] == "1843"
        assert [creator["creatorType"] for creator in items[EDITED]["creators"]] == [
            "author",
            "translator",
        ], "The browser's creators did not reach the desktop"
        assert sorted(tag["tag"] for tag in items[EDITED]["tags"]) == ["engine", "translation"]
        assert related_to(items[EDITED]) == [f"http://zotero.org/users/1/items/{RELATED}"], (
            "The desktop does not see the relation"
        )
        assert related_to(items[RELATED]) == [f"http://zotero.org/users/1/items/{EDITED}"], (
            "The relation was written on one side only"
        )
        assert items[RELATED]["itemType"] == "report"
        assert items[made]["itemType"] == "journalArticle"
        assert items[made]["title"] == "Made in a browser"

        # The race: the browser has read the item; a desktop changes it first.
        stale = await version(EDITED)
        await run.phase(
            "B", [dict(action="edit", key=EDITED, fields=dict(date="1842"))], files=False
        )
        refused = await browser.patch(
            f"/items/{EDITED}", json=dict(version=stale, fields=dict(date="1844"))
        )
        assert refused.status_code == 412, refused.text
        current = (await browser.get(f"/items/{EDITED}")).json()["data"]
        assert current["date"] == "1842", "The desktop's edit was written over"

    await run.settled(files=False)
