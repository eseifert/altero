"""Review every discovered desktop network consumer and retain runtime evidence."""

import hashlib
import json
from collections import Counter
from pathlib import Path

from tools.compatibility.analyze import source_files
from tools.compatibility.client import CompatibilityError, ZoteroClient, read_inside, run_node

REVIEW = Path(__file__).with_name("interactions.json")
PATTERNS = ["chrome/content/**/*.js", "resource/**/*.js", "resource/**/*.mjs"]
STATUSES = {"supported", "pending", "unsupported", "external", "transport"}


def interactions(client: ZoteroClient, *, review_path=REVIEW, server_root=None) -> dict:
    client.verify_revision()
    files = source_files(client.root, PATTERNS, [])
    sources = [dict(file=file, source=read_inside(client.root, file)) for file in files]
    result: dict = dict(calls=[], errors=[])
    # Bound each parser process; one complex file must not hide the rest.
    for start in range(0, len(sources), 12):
        batch = sources[start : start + 12]
        try:
            indexed = run_node(dict(operation="network", files=batch), timeout=30)
            result["calls"].extend(indexed["calls"])
            result["errors"].extend(indexed["errors"])
        except CompatibilityError as error:
            result["errors"].extend(dict(file=source["file"], error=str(error)) for source in batch)
    reviewed = json.loads(review_path.read_text()) if review_path.is_file() else {}
    consumers = {}
    for call in result["calls"]:
        identity = call["file"] + "::" + call["selector"]
        consumers.setdefault(identity, []).append(call)
    entries = []
    root = server_root or Path(__file__).resolve().parents[2]
    hashes = {s["file"]: hashlib.sha256(s["source"].encode()).hexdigest() for s in sources}
    for identity, calls in consumers.items():
        digest = hashlib.sha256(
            (hashes[calls[0]["file"]] + json.dumps(calls, sort_keys=True)).encode()
        ).hexdigest()
        declaration = reviewed.get("consumers", {}).get(identity, {})
        status = declaration.get("status", "unreviewed")
        if declaration.get("sha256") != digest:
            status = "unreviewed"
        if status != "unreviewed":
            if status not in STATUSES or not declaration.get("reason", "").strip():
                raise CompatibilityError(f"Invalid interaction review: {identity}")
            if status == "supported" and not declaration.get("tests"):
                raise CompatibilityError(f"Supported interaction needs evidence: {identity}")
            for test in declaration.get("tests", []):
                path = (root / test.split("::", 1)[0]).resolve()
                if not path.is_relative_to(root.resolve()) or not path.is_file():
                    raise CompatibilityError(f"Interaction evidence is unavailable: {test}")
        entries.append(
            dict(
                identity=identity,
                sha256=digest,
                status=status,
                calls=calls,
                reason=declaration.get("reason"),
                tests=declaration.get("tests", []),
            )
        )
    stale = sorted(set(reviewed.get("consumers", {})) - consumers.keys())
    return dict(
        revision=client.manifest["zotero"]["revision"],
        files=[
            dict(file=s["file"], sha256=hashlib.sha256(s["source"].encode()).hexdigest())
            for s in sources
        ],
        consumers=entries,
        counts=dict(Counter(entry["status"] for entry in entries)),
        errors=result["errors"],
        stale=stale,
        evidence="Reviewed call sites, not passing tests or exhaustive call-graph analysis",
    )


def require_reviewed(report: dict) -> None:
    if report["errors"] or report["stale"] or report["counts"].get("unreviewed", 0):
        raise CompatibilityError(
            "Desktop interactions have parse errors, stale or unreviewed consumers"
        )


def markdown(report: dict) -> str:
    lines = [
        "# Desktop network interactions",
        "",
        report["evidence"],
        "",
        "| Consumer | Status | Calls | Evidence / reason |",
        "|---|---|---|---|",
    ]
    for entry in report["consumers"]:
        calls = "; ".join(f"{c['method']} {c['uri']}" for c in entry["calls"])
        detail = ", ".join(entry["tests"]) or entry["reason"] or "Needs review"
        calls = calls.replace("|", "&#124;").replace("\n", " ").replace("\r", " ")
        lines.append(f"| {entry['identity']} | {entry['status']} | {calls} | {detail} |")
    lines += ["", "## Source errors", "", *[str(error) for error in report["errors"]]]
    return "\n".join(lines) + "\n"
