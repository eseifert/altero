"""Valid deterministic wire payloads derived from the vendored Zotero schema."""

import json
from pathlib import Path

SCHEMA = Path(__file__).resolve().parents[2] / "src/altero/itemschema/data/schema.json"


def schema_corpus() -> list[dict]:
    corpus = []
    for index, definition in enumerate(json.loads(SCHEMA.read_text())["itemTypes"]):
        kind = definition["itemType"]
        payload = {
            "key": f"TEST{index + 2:04d}".replace("0", "A").replace("1", "B"),
            "itemType": kind,
        }
        for entry in definition["fields"]:
            field = entry["field"]
            payload[field] = {"accessDate": "2026-09-29T12:34:56Z", "date": "2026-09-29"}.get(
                field, f"{field}: Über 東京 🐝"
            )
        if definition["creatorTypes"]:
            payload["creators"] = [
                {"creatorType": entry["creatorType"], "name": f"研究 {entry['creatorType']}"}
                for entry in definition["creatorTypes"]
            ]
        payload.update(
            tags=[{"tag": "研究 🐝", "type": 1}],
            relations={"dc:relation": "https://example.org/研究"},
            dateAdded="2026-09-29T12:34:56Z",
            dateModified="2026-09-30T23:45:01Z",
        )
        if kind == "note":
            payload["note"] = "<p>Über 東京 🐝</p>"
        elif kind == "attachment":
            payload.update(
                linkMode="imported_file", contentType="application/pdf", filename="研究.pdf"
            )
        elif kind == "annotation":
            payload.update(
                parentItem="TESTAAA4",
                annotationType="highlight",
                annotationText="東京",
                annotationComment="Über",
                annotationColor="#ffd400",
                annotationPageLabel="1",
                annotationSortIndex="00000|000001|00000",
                annotationPosition='{"pageIndex":0,"rects":[[1,2,3,4]]}',
            )
        corpus.append(payload)
    return corpus
