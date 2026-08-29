"""The version is written once and everything else is held to it.

`src/altero/__init__.py` is the copy that is served -- from `/health`, from the
OpenAPI document, and stamped into every library archive -- so it is the one
that has to be right. `pyproject.toml` reads it from there, but the web
interface's `package.json` cannot, and the two spell the same version
differently: PEP 440 writes a prerelease `1.0.0a2`, npm writes `1.0.0-alpha.2`.
They drifted once already, which is why this is a test rather than a habit.
"""

import json
import re
import tomllib
from pathlib import Path

import pytest

import altero

ROOT = Path(__file__).resolve().parent.parent

#: PEP 440 prerelease spellings and what npm calls each of them.
PRERELEASE_NAMES = {"a": "alpha", "b": "beta", "rc": "rc"}


def npm_version(version: str) -> str:
    """Return ``version``, a PEP 440 version, spelled the way npm spells it."""
    match = re.fullmatch(r"(\d+\.\d+\.\d+)(?:(a|b|rc)(\d+))?", version)
    if match is None:
        pytest.fail(f"{version!r} is not a release or prerelease this project knows how to spell")
    release, kind, number = match.groups()
    if kind is None:
        return release
    return f"{release}-{PRERELEASE_NAMES[kind]}.{number}"


def test_pyproject_takes_its_version_from_the_package() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert "version" in metadata["project"]["dynamic"]
    assert metadata["tool"]["hatch"]["version"]["path"] == "src/altero/__init__.py"


@pytest.mark.parametrize("name", ["package.json", "package-lock.json"])
def test_the_web_interface_carries_the_same_version(name: str) -> None:
    manifest = json.loads((ROOT / "web" / name).read_text())

    assert manifest["version"] == npm_version(altero.__version__)
