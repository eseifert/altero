"""Check release metadata before tagging or publishing; uses only the standard library."""

import argparse
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRERELEASE_NAMES = {"a": "alpha", "b": "beta", "rc": "rc"}


def check_release(root: Path, tag: str | None = None) -> str:
    """Return the expected tag, refusing inconsistent versions or missing release notes."""
    source = (root / "src/altero/__init__.py").read_text()
    match = re.search(r'^__version__ = "(\d+\.\d+\.\d+)(?:(a|b|rc)(\d+))?"$', source, re.M)
    if match is None:
        raise ValueError("Package version must use the project's PEP 440 release spelling")
    version, kind, number = match.groups()
    if kind:
        version += f"-{PRERELEASE_NAMES[kind]}.{number}"
    expected_tag = f"v{version}"
    if tag is not None and tag != expected_tag:
        raise ValueError(f"Tag {tag!r} does not match package version {expected_tag!r}")

    for name in ("package.json", "package-lock.json"):
        manifest = json.loads((root / "web" / name).read_text())
        if manifest["version"] != version:
            raise ValueError(f"web/{name} version does not match {version}")
        if name == "package-lock.json" and manifest["packages"][""]["version"] != version:
            raise ValueError(f"web/{name} root package version does not match {version}")

    changelog = (root / "CHANGELOG.md").read_text()
    headings = re.findall(r"^## \[([^]]+)\]", changelog, re.M)
    released = [heading for heading in headings if heading != "Unreleased"]
    if not headings or headings[0] != "Unreleased" or not released or released[0] != version:
        raise ValueError(f"CHANGELOG.md must start with Unreleased followed by {version}")
    notes = re.search(
        rf"^## \[{re.escape(version)}\] — (\d{{4}}-\d{{2}}-\d{{2}})\n(.*?)(?=^## |\Z)",
        changelog,
        re.M | re.S,
    )
    if notes is None:
        raise ValueError(f"CHANGELOG.md needs dated release notes for {version}")
    try:
        date.fromisoformat(notes[1])
    except ValueError as exc:
        raise ValueError("CHANGELOG.md release date is invalid") from exc
    if not re.search(r"^- ", notes[2], re.M):
        raise ValueError(f"CHANGELOG.md needs changes listed for {version}")
    link = f"[{version}]: https://github.com/eseifert/altero/releases/tag/{expected_tag}"
    if link not in changelog.splitlines():
        raise ValueError(f"CHANGELOG.md needs the release link for {expected_tag}")
    return expected_tag


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="Also verify the tag being published, including its v prefix")
    args = parser.parse_args()
    try:
        tag = check_release(ROOT, args.tag)
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(1, f"Release check failed: {exc}\n")
    print(f"Release metadata consistent: {tag}")


if __name__ == "__main__":
    main()
