"""Coverage is an explicit scenario inventory, never inferred from route counts."""

import pytest

from tools.compatibility.client import CompatibilityError
from tools.compatibility.surface import inventory


def test_untested_scenarios_remain_visible() -> None:
    result = inventory()
    gaps = [s for s in result["scenarios"] if s["status"] != "executable"]
    assert any(s["name"] == "retractions" for s in gaps)
    assert all(s["reason"] for s in gaps)
    assert result["counts"]["executable"] > 0
    assert any(s["operation"] == "streaming" for s in result["scenarios"])
    assert sum(result["counts"].values()) == len(result["scenarios"])


@pytest.mark.parametrize(
    "scenario",
    [
        {"operation": "read", "status": "executable", "tests": ["missing.py"]},
        {"operation": "read", "status": "unsupported"},
        {"operation": "read", "status": "green"},
    ],
)
def test_invalid_coverage_cannot_claim_success(tmp_path, scenario) -> None:
    with pytest.raises(CompatibilityError):
        inventory(root=tmp_path, scenarios={"bad": scenario})
