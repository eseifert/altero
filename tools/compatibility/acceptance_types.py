"""An item whose type changes, losing fields, syncs from one desktop to the other."""

from tools.compatibility.acceptance_runtime import AcceptanceRun


async def type_change(run: AcceptanceRun) -> None:
    """The desktop's own mapping, uploaded as a patch, is stored as it was meant.

    `setType` moves the publisher to a film's distributor, the author to its
    director and the editor to contributor, and drops the edition. The patch
    then blanks `edition` and `publisher` -- fields a film does not have --
    which the server must take as a clear rather than refuse.
    """
    await run.phase(
        "A",
        [
            dict(
                action="create",
                key="RETYPE23",
                data=dict(
                    itemType="book",
                    title="Structure and Interpretation",
                    edition="2",
                    publisher="MIT Press",
                    creators=[
                        dict(creatorType="author", firstName="Harold", lastName="Abelson"),
                        dict(creatorType="editor", firstName="Ed", lastName="Itor"),
                    ],
                ),
            )
        ],
        files=False,
    )
    await run.phase("B", files=False)

    changed = await run.phase(
        "A", [dict(action="retype", key="RETYPE23", itemType="film")], files=False
    )
    assert not changed["unsynced"]["item"], "The type change did not upload"
    remote = (await run.request("GET", "/users/1/items/RETYPE23")).json()["data"]
    assert remote["itemType"] == "film"
    assert remote["distributor"] == "MIT Press", "The publisher did not move to distributor"
    assert not {"edition", "publisher"} & set(remote), "Fields a film lacks were kept"
    assert [creator["creatorType"] for creator in remote["creators"]] == [
        "director",
        "contributor",
    ]
    await run.converged(changed, await run.phase("B", files=False))
    await run.settled(files=False)
