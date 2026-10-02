"""Turn retained acceptance evidence into a version-specific result matrix."""

import hashlib
import json
from pathlib import Path

from tools.compatibility.acceptance import SCENARIOS
from tools.compatibility.client import CompatibilityError


def collect(paths: list[Path], version: str) -> dict:
    cells = {}
    for path in paths:
        raw = path.read_bytes()
        report = json.loads(raw)
        if report.get("desktop_version") != version:
            raise CompatibilityError(f"Desktop version mismatch: {path}")
        backend = report.get("database_backend")
        if backend is None:
            # Older reports retain backend evidence alongside each server.
            backends = set()
            for name in report["scenarios"]:
                server = path.parent / name / "server"
                metadata = server / "database.json"
                if metadata.is_file():
                    backends.add(json.loads(metadata.read_text()).get("backend"))
                elif (server / "server.sqlite").is_file():
                    backends.add("sqlite")
            if len(backends) == 1:
                backend = backends.pop()
        if backend not in {"sqlite", "postgresql"}:
            raise CompatibilityError(f"Missing database backend: {path}")
        for name, scenario in report["scenarios"].items():
            if name not in SCENARIOS:
                raise CompatibilityError(f"Unknown scenario: {name}")
            passed = scenario.get("passed") is True
            phases = scenario.get("phases", [])
            digest = hashlib.sha256()
            if passed:
                if not phases:
                    raise CompatibilityError(f"Passing scenario has no phases: {name}")
                root = (path.parent / name).resolve()
                for phase in phases:
                    snapshot_path = (root / phase["snapshot"]).resolve()
                    if not snapshot_path.is_relative_to(root) or not snapshot_path.is_file():
                        raise CompatibilityError(f"Missing or unsafe snapshot: {snapshot_path}")
                    snapshot_raw = snapshot_path.read_bytes()
                    snapshot = json.loads(snapshot_raw)
                    if snapshot.get("interrupted"):
                        if snapshot["interrupted"] is not True or snapshot.get("exit_status") != -9:
                            raise CompatibilityError(
                                f"Invalid interruption evidence: {snapshot_path}"
                            )
                    elif snapshot.get("version") != version:
                        raise CompatibilityError(f"Snapshot version mismatch: {snapshot_path}")
                    digest.update(phase["snapshot"].encode() + b"\0" + snapshot_raw)
            cell = dict(
                scenario=name,
                backend=backend,
                status="passed" if passed else "failed",
                phases=len(phases),
                report_sha256=hashlib.sha256(raw).hexdigest(),
                snapshots_sha256=digest.hexdigest() if passed else None,
                finished_at=report.get("finished_at"),
            )
            key = (name, backend)
            # A retained failure never erases a completed successful reproduction.
            if key not in cells or passed:
                cells[key] = cell
    return dict(desktop_version=version, cells=list(cells.values()))


def markdown(result: dict) -> str:
    cells = {(cell["scenario"], cell["backend"]): cell for cell in result["cells"]}
    lines = [
        f"Zotero {result['desktop_version']} Linux x86-64; actual desktop profiles.",
        "",
        "| Scenario | SQLite | PostgreSQL |",
        "|---|---|---|",
    ]
    for name in SCENARIOS:
        row = []
        for backend in ("sqlite", "postgresql"):
            cell = cells.get((name, backend))
            row.append(
                "Not run"
                if cell is None
                else f"Passed ({cell['phases']} phases)"
                if cell["status"] == "passed"
                else "Failed"
            )
        lines.append(f"| `{name}` | {' | '.join(row)} |")
    return "\n".join(lines) + "\n"
