"""Settings reach desktop caches and survive delete/recreate while offline."""

from tools.compatibility.acceptance_runtime import AcceptanceRun


async def settings(run: AcceptanceRun) -> None:
    first = await run.phase(
        "A",
        [
            dict(action="tag-color", name="研究", color="#123456"),
            dict(action="tag-color", name="urgent", color="#ff6666"),
        ],
        files=False,
    )
    await run.converged(first, await run.phase("B", files=False))
    await run.phase(
        "A",
        [dict(action="tag-color", name="urgent", color="#009900", position=0)],
        files=False,
        sync=False,
    )
    await run.phase(
        "B", [dict(action="tag-color", name="研究", color="#000099")], files=False, sync=False
    )
    remote = await run.phase("A", files=False)
    downloaded = await run.phase("B", files=False)
    # The desktop downloads the current setting over a stale local setting on 412.
    await run.converged(remote, downloaded)
    assert downloaded["tag_colors"]["urgent"] == dict(color="#009900", position=0)
    assert downloaded["tag_colors"]["研究"] == dict(color="#123456", position=1)
    await run.phase("A", [dict(action="setting", name="tagColors", value=None)], files=False)
    restored = await run.phase(
        "A", [dict(action="tag-color", name="returned", color="#123456")], files=False
    )
    returned = await run.phase("B", files=False)
    await run.converged(restored, returned)
    assert returned["tag_colors"] == {"returned": dict(color="#123456", position=0)}
    await run.settled(files=False)
