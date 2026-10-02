"""Index actual HTML and verify the downloaded index in a file-less profile."""

from tools.compatibility.acceptance_runtime import AcceptanceRun


def indexed(snapshot: dict, key: str, word: str) -> None:
    row = snapshot["fulltext"].get(key)
    assert row, "Desktop has no persisted full-text row"
    assert word in row["matches"], "Synced content did not reach the desktop search index"
    assert row["synced"] == 1, "Full-text content remains pending"
    assert row["version"] > 0, "Full-text content has no synced version"


async def fulltext(run: AcceptanceRun) -> None:
    async def phase(name, operations=(), **options):
        return await run.phase(
            name, operations, fulltext_terms=("compatibilityneedle", "Über", "東京"), **options
        )

    assets = run.root / "snapshot-source"
    assets.mkdir()
    path = assets / "index.html"
    path.write_text(
        '<html><head><meta charset="UTF-8"></head><body><p>compatibilityneedle '
        "Über 東京</p></body></html>"
    )
    created = await phase(
        "A",
        [
            dict(action="create", key="TEXT2345"),
            dict(action="snapshot", key="TEXT2345", path=str(path)),
        ],
        fulltext=False,
    )
    key = next(item["key"] for item in created["items"] if item["itemType"] == "attachment")
    uploaded = await phase("A", [dict(action="index", key=key)], files=False, fulltext=True)
    indexed(uploaded, key, "compatibilityneedle")
    stored = (await run.request("GET", f"/users/1/items/{key}/fulltext")).json()
    assert "compatibilityneedle" in stored["content"]
    # B has no attachment bytes. Only the server's full-text response can supply its index.
    downloaded = await phase("B", files=False, fulltext=True)
    for word in ("compatibilityneedle", "Über", "東京"):
        indexed(downloaded, key, word)
    assert not (run.root / "B" / "data" / "storage" / key / "index.html").exists()
    indexed(await phase("B", files=False, fulltext=False), key, "compatibilityneedle")
    indexed(await phase("B", files=False, fulltext=True), key, "compatibilityneedle")
    await run.converged(await phase("A", fulltext=True), await phase("B", fulltext=True))
    await run.settled(fulltext=True)
