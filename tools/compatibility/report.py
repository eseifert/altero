"""A review artifact that never upgrades a static suspicion to a verified bug."""

from typing import Any


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Desktop compatibility source analysis",
        "",
        f"Pinned checkout: {'yes' if report['pinned'] else 'no'}.",
        "",
        f"{len(report['findings'])} possible omissions, "
        f"{len(report['unmapped'])} unmapped consumers, "
        f"{len(report['errors'])} source errors. Findings require an executable reproducer.",
        "",
        "## Possible omissions",
        "",
    ]
    for finding in report["findings"]:
        client, server = finding["client"], finding["server"]
        lines.append(
            f"- `{finding['contract']}` reads `{finding['field']}` at "
            f"`{client['file']}:{client['line']}`; `{server['function']}` at "
            f"`{server['file']}:{server['line']}` does not statically emit it. Unverified."
        )
    if not report["findings"]:
        lines.append("No omissions found in the mapped static comparisons.")
    lines.extend(["", "## Contracts", ""])
    for contract in report["contracts"]:
        lines.append(f"- `{contract['name']}`: {contract['status']}.")
    lines.extend(["", "## Unmapped consumers", ""])
    lines.extend(
        f"- `{entry['file']}:{entry['line']}`: `{entry['selector']}`."
        for entry in report["unmapped"]
    )
    lines.extend(["", "## Source errors", ""])
    lines.extend(f"- {entry}" for entry in report["errors"])
    if report["revision_error"]:
        lines.extend(["", str(report["revision_error"])])
    if "review_findings" in report:
        lines.extend(["", "## Automated review hypotheses", ""])
        for finding in report["review_findings"]:
            lines.extend(
                [
                    f"- {finding['summary']} Unverified.",
                    f"  Reproduction: {finding['reproduction']}",
                ]
            )
    if "reference" in report:
        reference = report["reference"]
        lines.extend(
            [
                "",
                "## Dataserver source cross-check",
                "",
                f"Revision: `{reference['revision']}`. Source reviewed; PHP was not executed.",
                "",
            ]
        )
        for check in reference["checks"]:
            lines.append(
                f"- {check['name']}: {check['status']}. {check['claim']} "
                f"(`{check['file']}:{check['line']}`)."
            )
    return "\n".join(lines) + "\n"
