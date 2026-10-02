"""Published passes must come from completed scenarios and the requested binary."""

import json

import pytest

from tools.compatibility.client import CompatibilityError
from tools.compatibility.matrix import collect, markdown


def report(root, *, passed=True, version="10.0.5", snapshot_version="10.0.5"):
    root.mkdir()
    scenario = root / "fulltext"
    scenario.mkdir()
    (scenario / "phase-1-A.json").write_text(json.dumps(dict(version=snapshot_version)))
    path = root / "acceptance.json"
    path.write_text(
        json.dumps(
            dict(
                passed=passed,
                desktop_version=version,
                database_backend="sqlite",
                scenarios=dict(
                    fulltext=dict(passed=passed, phases=[dict(snapshot="phase-1-A.json")])
                ),
            )
        )
    )
    return path


def test_only_completed_scenarios_become_passes(tmp_path):
    path = report(tmp_path / "run", passed=False)
    result = collect([path], "10.0.5")
    assert result["cells"][0]["status"] == "failed"
    assert "Passed" not in markdown(result)


def test_completed_subset_of_failed_run_can_be_reported(tmp_path):
    path = report(tmp_path / "run")
    value = json.loads(path.read_text())
    value["passed"] = False
    path.write_text(json.dumps(value))
    result = collect([path], "10.0.5")
    cell = result["cells"][0]
    assert cell["status"] == "passed"
    assert cell["phases"] == 1
    assert len(cell["report_sha256"]) == 64


@pytest.mark.parametrize("defect", ["binary", "snapshot", "missing", "empty", "backend", "escape"])
def test_invalid_evidence_cannot_claim_success(tmp_path, defect):
    path = report(tmp_path / "run")
    value = json.loads(path.read_text())
    scenario = value["scenarios"]["fulltext"]
    if defect == "binary":
        value["desktop_version"] = "10.0.1"
    elif defect == "snapshot":
        (path.parent / "fulltext" / "phase-1-A.json").write_text('{"version":"10.0.1"}')
    elif defect == "missing":
        scenario["phases"][0]["snapshot"] = "missing.json"
    elif defect == "empty":
        scenario["phases"] = []
    elif defect == "backend":
        value.pop("database_backend")
    else:
        scenario["phases"][0]["snapshot"] = "../../acceptance.json"
    path.write_text(json.dumps(value))
    with pytest.raises(CompatibilityError):
        collect([path], "10.0.5")
