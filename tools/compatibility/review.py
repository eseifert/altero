"""A provider-neutral JSON interface for optional automated source review."""

import copy
import json
import subprocess
from typing import Any

from tools.compatibility.client import CompatibilityError


def evidence(report: dict[str, Any], *, source_budget: int = 64_000) -> dict[str, Any]:
    """Bound source text; retain positions and explicitly mark clipping."""
    contracts = copy.deepcopy([c for c in report["contracts"] if "client" in c])
    unmapped = copy.deepcopy(report["unmapped"])
    for item in [*contracts, *unmapped]:
        blocks = [item["client"]] if "client" in item else [item]
        blocks.extend(item.get("server_evidence", []))
        for block in blocks:
            key = "code" if "code" in block else "source"
            original = block.get(key, "") or ""
            block[key] = original[:source_budget]
            block["truncated"] = len(original) > source_budget
            source_budget = max(0, source_budget - len(block[key]))
    return {
        "schema": 1,
        "task": (
            "Compare client decisions with server behavior. "
            "Report hypotheses with source references "
            "and a concrete reproduction. Missing optional fields are not automatically bugs. "
            "Respect documented exceptions. Propose tests for defaults, types and cached versions. "
            "Truncated or unresolved evidence needs investigation. Do not claim a test was run."
        ),
        "response_schema": {
            "findings": [
                {
                    "contract": "manifest name, or null for an unmapped consumer",
                    "summary": "hypothesis",
                    "client": {"file": "supplied path", "line": "integer"},
                    "server": {"file": "supplied path", "line": "integer"},
                    "reproduction": "setup, action and expected client behavior",
                }
            ],
        },
        "contracts": contracts,
        "unmapped": unmapped,
    }


def review(packet: dict[str, Any], command: list[str]) -> list[dict[str, Any]]:
    """Run the explicitly selected program without a shell or generated code execution."""
    if not command:
        raise CompatibilityError("The automated review command is empty")
    try:
        result = subprocess.run(
            command,
            input=json.dumps(packet),
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CompatibilityError(f"Automated review failed: {error}") from error
    if result.returncode:
        raise CompatibilityError(f"Automated review failed: {result.stderr.strip()}")
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise CompatibilityError("Invalid automated review JSON") from error
    if not isinstance(output, dict) or not isinstance(output.get("findings"), list):
        raise CompatibilityError("Automated review JSON needs a findings array")
    contracts = {c["name"]: c for c in packet["contracts"]}
    checked = []
    for finding in output["findings"]:
        if not isinstance(finding, dict) or "contract" not in finding:
            raise CompatibilityError("Each automated review finding must be an object")
        name = finding.get("contract")
        if name is None:
            clients = packet["unmapped"]
            servers = [s for c in packet["contracts"] for s in c.get("server_evidence", [])]
            servers.extend(s for c in packet["unmapped"] for s in c.get("server_evidence", []))
        elif isinstance(name, str) and name in contracts:
            clients = [contracts[name]["client"]]
            servers = contracts[name].get("server_evidence", [])
        else:
            raise CompatibilityError(f"Unknown review contract: {name}")
        for label, blocks in (("client", clients), ("server", servers)):
            reference = finding.get(label)
            if not isinstance(reference, dict) or not any(
                reference.get("file") == block["file"]
                and type(reference.get("line")) is int
                and block["line"] <= reference["line"] <= block["end_line"]
                for block in blocks
            ):
                raise CompatibilityError(f"Invalid {label} source reference in automated review")
        for key in ("summary", "reproduction"):
            if not isinstance(finding.get(key), str) or not finding[key].strip():
                raise CompatibilityError(f"Automated review needs {key}")
        checked.append(
            {
                key: finding[key]
                for key in ("contract", "summary", "client", "server", "reproduction")
            }
            | {"status": "unverified"}
        )
    return checked
