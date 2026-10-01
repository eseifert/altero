"""Small protocol mutation catalogue: known omissions must fail their canaries."""

import asyncio
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from tools.compatibility.client import CompatibilityError

CATALOGUE = {
    "missing-watermark": ("versions", "getVersions", {"mutation": "drop-watermark"}),
    "truncated-versions": ("versions", "getVersions", {"mutation": "truncate-list"}),
    "missing-success": (
        "write_report",
        "uploadObjects",
        {"mutation": "drop-field", "field": "successful"},
    ),
    "missing-deletion": ("deletion", "getDeleted", {"mutation": "drop-field", "field": "items"}),
    "empty-as-absent": ("clearing", "uploadObjects", {"mutation": "empty-as-absent"}),
    "frozen-watermark": ("versions", "getVersions", {"mutation": "set-watermark", "value": "0"}),
    "missing-roster": ("roster", "getGroup", {"mutation": "drop-data-field", "field": "members"}),
}


def injected_faults(method: str) -> list[dict]:
    name = os.environ.get("ALTERO_COMPAT_MUTATION")
    if not name:
        return []
    if name not in CATALOGUE:
        raise CompatibilityError(f"Unknown compatibility mutation: {name}")
    _, target, fault = CATALOGUE[name]
    return [fault] if method == target else []


async def run_mutations(source: Path, root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=False)
    observations = []
    for name, (test, _, _) in CATALOGUE.items():
        target = f"compatibility_tests/test_mutation_canaries.py::test_{test}"
        for mode in ("baseline", "mutated"):
            path = root / f"{name}-{mode}.xml"
            environment = dict(os.environ)
            environment.pop("ALTERO_COMPAT_MUTATION", None)
            if mode == "mutated":
                environment["ALTERO_COMPAT_MUTATION"] = name
            with (root / f"{name}-{mode}.log").open("wb") as log:
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    target,
                    "--zotero-source",
                    str(source),
                    f"--junitxml={path}",
                    stdout=log,
                    stderr=log,
                    env=environment,
                )
                try:
                    async with asyncio.timeout(120):
                        code = await process.wait()
                except BaseException:
                    if process.returncode is None:
                        process.kill()
                    await process.wait()
                    raise
            if not path.is_file():
                raise CompatibilityError(f"Mutation runner produced no JUnit: {name}/{mode}")
            xml = ET.parse(path)
            cases = xml.findall(".//testcase")
            failures = xml.findall(".//failure")
            errors = xml.findall(".//error")
            skipped = xml.findall(".//skipped")
            expected = (
                code == 0 and not failures
                if mode == "baseline"
                else code == 1 and len(failures) == len(cases)
            )
            if not cases or errors or skipped or not expected:
                raise CompatibilityError(
                    f"Mutation {name}/{mode} did not produce the required assertion outcome; "
                    f"inspect {root}"
                )
            if mode == "mutated":
                if not all(
                    "AssertionError" in (failure.get("message", "") + (failure.text or ""))
                    for failure in failures
                ):
                    raise CompatibilityError(f"Mutation {name} failed for an unrelated exception")
                observations.append(
                    {
                        "name": name,
                        "baseline_passed": True,
                        "mutation_detected": True,
                        "failures": len(failures),
                    }
                )
    return {
        "kind": "protocol mutations, not production source mutations",
        "mutations": observations,
    }
