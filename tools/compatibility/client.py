"""Run original Zotero functions with JSON arguments in a short-lived Node process."""

import hashlib
import json
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any

DEFAULT_MANIFEST = Path(__file__).with_name("contracts.toml")
RUNNER = Path(__file__).with_name("run_client.mjs")


class CompatibilityError(ValueError):
    """The source, selected function or invocation could not be checked."""


def read_inside(root: Path, relative: str) -> str:
    """Resolve links as well as ``..`` before reading a source file."""
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise CompatibilityError(f"Source must be inside {root}: {relative}")
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise CompatibilityError(f"Cannot read {path}: {error}") from error


def run_node(request: dict[str, Any]) -> Any:
    """JSON is the boundary; neither arguments nor source enter a shell command."""
    try:
        process = subprocess.run(
            ["node", str(RUNNER)],
            input=json.dumps(request),
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError as error:
        raise CompatibilityError("Node 24+ is required for client compatibility checks") from error
    except subprocess.TimeoutExpired as error:
        raise CompatibilityError("Client invocation timed out after 10 seconds") from error
    if process.returncode:
        raise CompatibilityError(process.stderr.strip() or "Client runner failed")
    try:
        return json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise CompatibilityError("Client runner did not return JSON") from error


class ZoteroClient:
    """Select functions from fingerprinted source without importing the desktop app."""

    def __init__(self, root: Path, manifest: Path = DEFAULT_MANIFEST) -> None:
        self.root = root.resolve()
        try:
            self.manifest = tomllib.loads(manifest.read_text())
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise CompatibilityError(f"Cannot read contract manifest: {error}") from error
        revision = self.manifest.get("zotero", {}).get("revision", "")
        if not isinstance(revision, str) or not re.fullmatch("[0-9a-f]{40}", revision):
            raise CompatibilityError("The manifest must pin a full Zotero commit id")
        contracts = self.manifest.get("contracts")
        if not isinstance(contracts, dict) or not contracts:
            raise CompatibilityError("The manifest must define contracts")
        for name, contract in contracts.items():
            for field in ("source", "selector", "sha256"):
                if not isinstance(contract.get(field), str) or not contract[field]:
                    raise CompatibilityError(f"Contract {name} needs {field}")
            if not re.fullmatch("[0-9a-f]{64}", contract["sha256"]):
                raise CompatibilityError(f"Contract {name} needs a SHA-256 fingerprint")

    def verify_revision(self) -> None:
        """A hash of each source additionally detects uncommitted changes."""
        try:
            actual = subprocess.check_output(
                ["git", "-C", str(self.root), "rev-parse", "HEAD"],
                text=True,
                stderr=subprocess.PIPE,
                timeout=10,
            ).strip()
        except (OSError, subprocess.SubprocessError) as error:
            raise CompatibilityError(f"Cannot identify Zotero revision in {self.root}") from error
        expected = self.manifest["zotero"]["revision"]
        if actual != expected:
            raise CompatibilityError(f"Zotero revision {actual} differs from pinned {expected}")

    def source(self, name: str, *, allow_drift: bool = False) -> tuple[dict[str, Any], str]:
        try:
            contract = self.manifest["contracts"][name]
        except KeyError as error:
            raise CompatibilityError(f"Unknown contract: {name}") from error
        source = read_inside(self.root, contract["source"])
        actual = hashlib.sha256(source.encode()).hexdigest()
        if not allow_drift and actual != contract["sha256"]:
            raise CompatibilityError(f"Source fingerprint changed for {name}; review the contract")
        return contract, source

    def extract(self, name: str, *, allow_drift: bool = False) -> dict[str, Any]:
        contract, source = self.source(name, allow_drift=allow_drift)
        return run_node(
            {"operation": "extract", "source": source, "selector": contract["selector"]}
        )

    def call(self, name: str, args: list[Any]) -> Any:
        contract, source = self.source(name)
        return run_node(
            {
                "operation": "call",
                "source": source,
                "selector": contract["selector"],
                "args": args,
            }
        )
