"""Keep the declared desktop scenarios and their remaining gaps reviewable."""

import tomllib
from pathlib import Path
from typing import Any

from tools.compatibility.client import CompatibilityError

SURFACE = Path(__file__).with_name("surface.toml")
ROOT = Path(__file__).resolve().parents[2]
STATUSES = ("executable", "desktop-runtime", "unsupported", "pending")


def inventory(*, root: Path = ROOT, scenarios: dict[str, Any] | None = None) -> dict[str, Any]:
    if scenarios is None:
        scenarios = tomllib.loads(SURFACE.read_text())["scenarios"]
    counts = dict.fromkeys(STATUSES, 0)
    entries = []
    for name, declaration in scenarios.items():
        status = declaration.get("status")
        if status not in STATUSES or not declaration.get("operation"):
            raise CompatibilityError(f"Invalid surface scenario: {name}")
        tests = declaration.get("tests", [])
        if status == "executable" and not tests:
            raise CompatibilityError(f"Executable scenario {name} needs tests")
        for test in tests:
            path = (root / test.split("::", 1)[0]).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():
                raise CompatibilityError(f"Scenario {name} has an unavailable test: {test}")
        if status != "executable" and not declaration.get("reason", "").strip():
            raise CompatibilityError(f"Scenario {name} needs a reason for {status}")
        counts[status] += 1
        entries.append(dict(name=name, **declaration))
    return dict(counts=counts, scenarios=entries, evidence="declared scenarios; not a test result")


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Desktop scenario coverage",
        "",
        "Executable means a scenario has tests; consult JUnit for their results.",
        "",
        "| Scenario | Operation | Status | Tests / reason |",
        "|---|---|---|---|",
    ]
    for scenario in report["scenarios"]:
        detail = ", ".join(scenario.get("tests", [])) or scenario.get("reason", "")
        lines.append(
            f"| {scenario['name']} | {scenario['operation']} | {scenario['status']} | {detail} |"
        )
    return "\n".join(lines) + "\n"
