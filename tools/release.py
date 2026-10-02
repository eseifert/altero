"""Check release metadata before tagging or publishing; uses only the standard library."""

import argparse
import json
import re
import tarfile
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRERELEASE_NAMES = {"a": "alpha", "b": "beta", "rc": "rc"}
SDIST_ROOTS = {
    "src",
    "migrations",
    "web",
    "tools",
    "tests",
    "compatibility_tests",
    "docs",
    "docker",
    ".github",
    ".gitignore",
    ".pre-commit-config.yaml",
    "alembic.ini",
    "config.example.py",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "zensical.toml",
    "uv.lock",
    "pyproject.toml",
    "README.md",
    "LICENSE",
    "PKG-INFO",
}


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


def check_artifacts(directory: Path, tag: str) -> None:
    """Verify the built wheel and source archive, including the browser interface."""
    version = tag.removeprefix("v")
    for python_name, web_name in PRERELEASE_NAMES.items():
        version = version.replace(f"-{web_name}.", python_name)
    wheels = list(directory.glob(f"altero-{version}-*.whl"))
    if len(wheels) != 1:
        raise ValueError(f"Expected one wheel for {tag} in {directory}")
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = wheel.namelist()
        metadata = wheel.read(f"altero-{version}.dist-info/METADATA").decode()
        if f"Version: {version}" not in metadata.splitlines():
            raise ValueError("Wheel metadata does not match the release version")
        index = "altero/web/static/index.html"
        if index not in names:
            raise ValueError("Wheel is missing the built browser interface")
        assets = re.findall(r'(?:src|href)="(/app/[^"?#]+)"', wheel.read(index).decode())
        if not any(asset.endswith(".js") for asset in assets):
            raise ValueError("Wheel browser index has no application script")
        for asset in assets:
            if f"altero/web/static/{asset.removeprefix('/app/')}" not in names:
                raise ValueError(f"Wheel browser index references missing asset {asset}")
        with tarfile.open(directory / f"altero-{version}.tar.gz") as source:
            members = {member.name: member for member in source.getmembers() if member.isfile()}
            prefix = f"altero-{version}/"
            for name in members:
                relative = name.removeprefix(prefix)
                if not name.startswith(prefix) or relative.split("/")[0] not in SDIST_ROOTS:
                    raise ValueError(f"Source archive includes unexpected file {name}")
            for name in names:
                if not name.startswith("altero/web/static/"):
                    continue
                member = members.get(f"{prefix}src/{name}")
                if member is None:
                    raise ValueError(f"Source archive is missing browser asset {name}")
                stream = source.extractfile(member)
                if stream is None or stream.read() != wheel.read(name):
                    raise ValueError(f"Source archive browser asset differs from wheel: {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="Also verify the tag being published, including its v prefix")
    parser.add_argument(
        "--artifacts", type=Path, help="Also verify the wheel and source archive here"
    )
    args = parser.parse_args()
    try:
        tag = check_release(ROOT, args.tag)
        if args.artifacts is not None:
            check_artifacts(args.artifacts, tag)
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(1, f"Release check failed: {exc}\n")
    print(f"Release metadata consistent: {tag}")


if __name__ == "__main__":
    main()
