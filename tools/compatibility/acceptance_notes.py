"""Notes: what the desktop's own editor writes, and notes written in a browser."""

import json
from pathlib import Path

from tools.compatibility.acceptance_reader import reader_pdf
from tools.compatibility.acceptance_runtime import AcceptanceRun
from tools.compatibility.note_corpus import CASES

BROWSER_NOTES = (
    Path(__file__).parents[2] / "web" / "src" / "notes" / "corpus" / "browser-notes.json"
)

# Zotero's key alphabet has no 0, 1 or O.
KEY_ALPHABET = "23456789ABCDEFGHIJKLMNPQRSTUVWXYZ"
PARENT = "NTPARNT2"
FROM_ANNOTATIONS = "ANNTATN2"


def notes(snapshot: dict) -> dict[str, dict]:
    return {item["key"]: item for item in snapshot["items"] if item["itemType"] == "note"}


async def note_corpus(run: AcceptanceRun) -> None:
    """Have the shipped note editor write every note in the corpus, and keep both.

    Each note is stored as a client wrote it, then opened in the desktop's item
    pane and saved by the editor itself, unedited; a note Zotero builds from a
    PDF's annotations is added the same way. The pairs are written to
    `note-corpus.json`, which `web/src/notes/corpus/` keeps for the web
    interface's editor to be held to.
    """
    keys = [
        f"NTCASE{KEY_ALPHABET[index // 32]}{KEY_ALPHABET[index % 32]}"
        for index in range(len(CASES))
    ]
    path = run.root / "notes.pdf"
    path.write_bytes(reader_pdf())
    first = await run.phase(
        "A",
        [
            dict(action="create", key=PARENT, data=dict(itemType="book", title="Notes on notes")),
            dict(action="attach", key=PARENT, path=str(path)),
            *(
                dict(action="create", key=key, data=dict(itemType="note", note=html))
                for key, (_, html) in zip(keys, CASES, strict=True)
            ),
        ],
    )
    attachment = next(item["key"] for item in first["items"] if item["itemType"] == "attachment")

    def annotation(kind: str, **fields) -> dict:
        # The type first: the desktop refuses any annotation field before it.
        return dict(
            itemType="annotation",
            parentItem=attachment,
            annotationType=kind,
            annotationColor="#ffd400",
            annotationPageLabel="1",
            annotationPosition='{"pageIndex":0,"rects":[[20,20,80,80]]}',
            **fields,
        )

    stored = notes(
        await run.phase(
            "A",
            [
                dict(
                    action="create",
                    key="HIGHLIT2",
                    data=annotation(
                        "highlight",
                        annotationText="A highlighted passage",
                        annotationComment="and a comment on it",
                        annotationSortIndex="00000|000001|00000",
                    ),
                ),
                dict(
                    action="create",
                    key="UNDERLN2",
                    data=annotation(
                        "underline",
                        annotationText="An underlined passage",
                        annotationSortIndex="00000|000002|00000",
                    ),
                ),
                dict(
                    action="create",
                    key="CMMNTN23",
                    data=annotation(
                        "note",
                        annotationComment="A note on the page",
                        annotationSortIndex="00000|000003|00000",
                    ),
                ),
                dict(action="note-from-annotations", key=FROM_ANNOTATIONS, attachment=attachment),
            ],
        )
    )
    names = dict(zip(keys, (name for name, _ in CASES), strict=True))
    names[FROM_ANNOTATIONS] = "made from annotations"

    written = notes(
        await run.phase("A", [dict(action="note-resave", keys=[*keys, FROM_ANNOTATIONS])])
    )

    # Three stages: what a client sent, what the desktop held before its editor
    # opened the note (a schema-1 note is upgraded on being shown), and what
    # the editor saved.
    sent = dict(zip(keys, (html for _, html in CASES), strict=True))
    sent[FROM_ANNOTATIONS] = stored[FROM_ANNOTATIONS]["note"]
    corpus = dict(
        desktop=run.version,
        cases=[
            dict(
                name=names[key],
                sent=sent[key],
                stored=stored[key]["note"],
                written=written[key]["note"],
            )
            for key in [*keys, FROM_ANNOTATIONS]
        ],
    )
    (run.root / "note-corpus.json").write_text(
        json.dumps(corpus, ensure_ascii=False, indent=1) + "\n"
    )

    # The server keeps every note exactly as the desktop wrote it.
    for key in [*keys, FROM_ANNOTATIONS]:
        served = (await run.request("GET", f"/users/1/items/{key}")).json()["data"]["note"]
        assert served == written[key]["note"], f"The server changed {names[key]}"
    await run.settled()


async def web_notes(run: AcceptanceRun) -> None:
    """Notes written through the browser's routes reach both desktops intact.

    The desktop's editor opens them editable and leaves them unwritten; a
    desktop's edit comes back to the browser. What the browser writes is held,
    in `web/src/notes/corpus.spec.ts`, to be exactly what its editor produces.
    """
    written = json.loads(BROWSER_NOTES.read_text())
    await run.phase(
        "A",
        [dict(action="create", key=PARENT, data=dict(itemType="book", title="Notes"))],
        files=False,
    )
    await run.phase("B", files=False)

    async with run.browser() as browser:

        async def write(body: dict, note: str) -> str:
            created = await browser.post("/items", json=body)
            created.raise_for_status()
            made = created.json()
            saved = await browser.patch(
                f"/items/{made['key']}", json=dict(version=made["version"], note=note)
            )
            saved.raise_for_status()
            return made["key"]

        standalone = await write(dict(itemType="note"), written["standalone"])
        child = await write(dict(itemType="note", parentItem=PARENT), written["child"])

        left, right = await run.phase("A", files=False), await run.phase("B", files=False)
        await run.converged(left, right)
        for snapshot in (left, right):
            seen = notes(snapshot)
            assert seen[standalone]["note"] == written["standalone"], (
                "A desktop changed the browser's note"
            )
            assert seen[child]["note"] == written["child"], "A desktop changed the browser's note"
            assert seen[child]["parentItem"] == PARENT

        viewed_path = run.root / "note-view.json"
        await run.phase(
            "B",
            [dict(action="note-view", keys=[standalone, child], path=str(viewed_path))],
            files=False,
        )
        for key, seen in json.loads(viewed_path.read_text()).items():
            assert not seen["readOnly"], f"The desktop opened {key} read-only"
            assert not seen["unsupportedSchema"], f"The desktop took {key} for a newer schema"
            assert not seen["written"], f"Opening {key} in the desktop wrote it"

        await run.phase(
            "A",
            [dict(action="note-resave", keys=[child], edit="append", text=" Desktop")],
            files=False,
        )
        changed = (await browser.get(f"/items/{child}")).json()["data"]["note"]
        assert "quoted Desktop" in changed, "The desktop's edit did not reach the browser"
        assert changed.startswith('<div data-schema-version="'), changed

    await run.settled(files=False)
