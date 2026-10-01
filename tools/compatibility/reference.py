"""Reviewed dataserver evidence, pinned separately from the desktop baseline."""

import hashlib
import subprocess
import tomllib
from pathlib import Path

from tools.compatibility.client import CompatibilityError

DEFAULT_REFERENCE = Path(__file__).with_name("reference.toml")


def reference_evidence(root: Path, manifest: Path = DEFAULT_REFERENCE) -> dict:
    config = tomllib.loads(manifest.read_text())
    try:
        revision = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        changes = subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"], text=True
        )
    except subprocess.CalledProcessError as error:
        raise CompatibilityError("Cannot inspect dataserver checkout") from error
    if revision != config["dataserver"]["revision"] or changes:
        raise CompatibilityError("Dataserver revision differs or tracked source changed")
    sources = {}
    for name, expected in config["files"].items():
        file = (root / name).resolve()
        if not file.is_relative_to(root.resolve()):
            raise CompatibilityError("Dataserver source path escapes checkout")
        content = file.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise CompatibilityError(f"Dataserver fingerprint differs: {name}")
        sources[name] = content.decode().splitlines(keepends=True)
    checks = []
    for check in config["checks"]:
        lines = sources[check["file"]]
        start, end = check["line"], check["end_line"]
        if not 1 <= start <= end <= len(lines):
            raise CompatibilityError(f"Invalid dataserver source range: {check['name']}")
        if check["status"] not in {"consistent", "documented-difference"}:
            raise CompatibilityError(f"Invalid reference status: {check['name']}")
        checks.append(check | {"code": "".join(lines[start - 1 : end])})
    return {"revision": revision, "executed": False, "checks": checks}
