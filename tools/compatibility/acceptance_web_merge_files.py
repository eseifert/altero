"""PDF deduplication reaches real desktop files, notes and annotation parents."""

import base64
import hashlib
from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

from tools.compatibility.acceptance_runtime import AcceptanceRun
from tools.compatibility.acceptance_web_merge import merge_review, relation, uri

TEXT = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima"


@dataclass(frozen=True)
class Case:
    name: str
    master_marked: bool = False
    other_marked: bool = False
    identical: bool = False
    note: bool = True
    annotate: int = 1
    keep: int | None = 0  # None keeps both PDFs; otherwise the index of the survivor.


@dataclass
class Record:
    case: Case
    parents: tuple[str, str]
    files: list[str]
    content: tuple[bytes, bytes]
    annotated: str
    annotation: str


CASES = (
    Case("identical", identical=True),
    Case("matching-text"),
    Case("marked-source", other_marked=True, keep=1, note=False, annotate=0),
    Case("marked-source-note", other_marked=True, keep=None, annotate=0),
    Case("both-marked", master_marked=True, other_marked=True, keep=None),
)


def pdf(text: str, marked: bool) -> bytes:
    """Make actual text and optional embedded markup, with no server parser calls."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 30 700 Td ({text}) Tj ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    if marked:
        page[NameObject("/Annots")] = ArrayObject(
            [
                writer._add_object(
                    DictionaryObject(
                        {
                            NameObject("/Type"): NameObject("/Annot"),
                            NameObject("/Subtype"): NameObject("/Text"),
                            NameObject("/Rect"): ArrayObject(
                                [NumberObject(n) for n in (20, 20, 40, 40)]
                            ),
                        }
                    )
                )
            ]
        )
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


async def web_merge_files(run: AcceptanceRun) -> None:
    parents = [(f"PDFMAS{letter}2", f"PDFDUP{letter}2") for letter in "ABCDE"]
    await run.phase(
        "A",
        [
            dict(
                action="create",
                key=key,
                data=dict(
                    itemType="book",
                    title=f"Paper about {case.name}",
                    dateAdded=f"{year}-01-01T00:00:00Z",
                ),
            )
            for case, pair in zip(CASES, parents, strict=True)
            for key, year in zip(pair, (2020, 2022), strict=True)
        ],
    )
    records: list[Record] = []
    async with run.browser() as browser:
        for case, pair, letter in zip(CASES, parents, "ABCDE", strict=True):
            original = pdf(TEXT, case.master_marked)
            other = (
                original
                if case.identical
                else pdf(" ".join(reversed(TEXT.split())), case.other_marked)
            )
            assert (hashlib.md5(original).digest() == hashlib.md5(other).digest()) == case.identical
            files: list[str] = []
            for index, (parent, content) in enumerate(zip(pair, (original, other), strict=True)):
                response = await browser.post(
                    "/attachments",
                    params=dict(
                        parentItem=parent,
                        filename=f"{case.name}-{index}.pdf",
                        mtime=1_700_000_000_000,
                    ),
                    content=content,
                    headers={"Content-Type": "application/pdf"},
                )
                response.raise_for_status()
                files.append(response.json()["key"])
            # Annotate the copy that will be discarded, including the reverse
            # case where the source's embedded markup makes its file survive.
            annotated = files[case.annotate]
            records.append(
                Record(
                    case=case,
                    parents=pair,
                    files=files,
                    content=(original, other),
                    annotated=annotated,
                    annotation=f"ANNTA{letter}23",
                )
            )

        await run.phase("A")
        await run.phase("B")
        operations = []
        for record in records:
            if record.case.note:
                operations.append(
                    dict(
                        action="json",
                        key=record.annotated,
                        data=dict(note=f"<p>Embedded note for {record.case.name}</p>"),
                    )
                )
            operations.extend(
                [
                    dict(
                        action="create",
                        key=record.annotation,
                        data=dict(
                            itemType="annotation",
                            parentItem=record.annotated,
                            annotationType="highlight",
                            annotationText=record.case.name,
                            annotationComment="Move this annotation with its PDF",
                            annotationColor="#ffd400",
                            annotationPageLabel="1",
                            annotationSortIndex="00000|000001|00000",
                            annotationPosition='{"pageIndex":0,"rects":[[20,20,80,40]]}',
                        ),
                    ),
                ]
            )
        before = await run.phase("A", operations)
        await run.converged(before, await run.phase("B"))
        before_items = {item["key"]: item for item in before["items"]}
        indexed = (await run.request("GET", "/users/1/fulltext", params=dict(since=0))).json()
        assert not {key for record in records for key in record.files} & set(indexed), (
            "PDF matching must exercise extraction rather than cached full text"
        )
        for record in records:
            master, duplicate = record.parents
            await merge_review(
                run, browser, master, duplicate, dict(title=f"Merged {record.case.name}")
            )

        left, right = await run.phase("A"), await run.phase("B")
        await run.converged(left, right)
        for record in records:
            case, pair, files = record.case, record.parents, record.files
            kept = files if case.keep is None else [files[case.keep]]
            for snapshot in (left, right):
                state = {item["key"]: item for item in snapshot["items"]}
                assert state[pair[1]].get("deleted"), "PDF merge left its duplicate record active"
                active = {
                    item["key"]
                    for item in state.values()
                    if item["itemType"] == "attachment"
                    and item.get("parentItem") == pair[0]
                    and not item.get("deleted")
                }
                assert active == set(kept), f"Incorrect surviving PDFs for {case.name}"
                assert relation(state[pair[0]], "dc:replaces") == {uri(pair[1])}
                expected_parent = record.annotated if case.keep is None else kept[0]
                assert state[record.annotation]["parentItem"] == expected_parent, (
                    f"PDF merge stranded the annotation for {case.name}"
                )
                assert state[expected_parent].get("note", "") == before_items[record.annotated].get(
                    "note", ""
                ), f"PDF merge lost the embedded note for {case.name}"
                if case.keep is not None:
                    discarded = files[1 - case.keep]
                    assert state[discarded].get("deleted"), (
                        f"PDF duplicate stayed active: {case.name}"
                    )
                    assert not state[discarded].get("note"), (
                        "Discarded attachment kept a copied note"
                    )
                    assert relation(state[kept[0]], "dc:replaces") == {uri(discarded)}
                for key in kept:
                    expected = base64.b64encode(record.content[files.index(key)]).decode()
                    assert snapshot["files"][key] == expected, (
                        f"Desktop changed PDF bytes: {case.name}"
                    )
                    assert snapshot["storage_states"][key] == "in_sync"
            for key in kept:
                served = await browser.get(f"/items/{key}/file")
                served.raise_for_status()
                assert served.content == record.content[files.index(key)]
    await run.settled()
