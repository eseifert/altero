"""External review stays provisional and must cite the supplied source."""

import sys
from pathlib import Path

import pytest

from tools.compatibility.client import CompatibilityError
from tools.compatibility.review import evidence, review


@pytest.fixture
def report() -> dict:
    return {
        "contracts": [
            {
                "name": "permissions",
                "status": "candidate",
                "tests": [],
                "client": {"file": "groups.js", "line": 2, "end_line": 5, "code": "client source"},
                "server_evidence": [
                    {
                        "file": "serializers.py",
                        "line": 10,
                        "end_line": 20,
                        "source": "server source",
                    }
                ],
            }
        ],
        "unmapped": [],
        "findings": [],
    }


def reviewer(
    tmp_path: Path, *, line: int = 3, contract: str | None = "permissions", file: str = "groups.js"
) -> list[str]:
    result = {
        "findings": [
            {
                "contract": contract,
                "summary": "Member identity is missing.",
                "client": {"file": file, "line": line},
                "server": {"file": "serializers.py", "line": 12},
                "reproduction": "Fetch metadata as a member and assert editable is true.",
                "status": "verified",
            }
        ]
    }
    script = tmp_path / "reviewer.py"
    script.write_text(
        "import json, sys\n"
        "request = json.load(sys.stdin)\n"
        "assert request['schema'] == 1\n"
        f"json.dump({result!r}, sys.stdout)\n"
    )
    return [sys.executable, str(script)]


def test_a_review_program_cannot_claim_its_finding_was_verified(
    report: dict, tmp_path: Path
) -> None:
    findings = review(evidence(report), reviewer(tmp_path))

    assert findings[0]["status"] == "unverified"
    assert findings[0]["summary"] == "Member identity is missing."


def test_references_outside_the_supplied_source_are_rejected(report: dict, tmp_path: Path) -> None:
    with pytest.raises(CompatibilityError, match="source reference"):
        review(evidence(report), reviewer(tmp_path, line=500))


def test_the_source_budget_marks_truncated_evidence(report: dict) -> None:
    packet = evidence(report, source_budget=5)

    assert packet["contracts"][0]["client"]["code"] == "clien"
    assert packet["contracts"][0]["client"]["truncated"]
    assert packet["contracts"][0]["server_evidence"][0]["source"] == ""


def test_a_failed_review_process_is_reported(report: dict) -> None:
    with pytest.raises(CompatibilityError, match="review failed"):
        review(evidence(report), [sys.executable, "-c", "raise SystemExit(1)"])


def test_invalid_review_json_is_rejected(report: dict) -> None:
    with pytest.raises(CompatibilityError, match="review JSON"):
        review(evidence(report), [sys.executable, "-c", "print('not JSON')"])


def test_a_review_can_propose_a_contract_for_an_unmapped_consumer(
    report: dict, tmp_path: Path
) -> None:
    report["unmapped"] = [
        {
            "file": "new.js",
            "line": 2,
            "end_line": 5,
            "code": "unmapped client source",
            "server_evidence": [],
        }
    ]

    findings = review(evidence(report), reviewer(tmp_path, contract=None, file="new.js"))

    assert findings[0]["contract"] is None
    assert findings[0]["status"] == "unverified"
