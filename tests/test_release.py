"""A tag must describe the package and have release notes before it is published."""

import json
from pathlib import Path

import pytest

from tools.release import check_release


def release_tree(root: Path, python_version: str, web_version: str) -> Path:
    (root / "src/altero").mkdir(parents=True)
    (root / "src/altero/__init__.py").write_text(f'__version__ = "{python_version}"\n')
    (root / "web").mkdir()
    (root / "web/package.json").write_text(json.dumps({"version": web_version}))
    (root / "web/package-lock.json").write_text(
        json.dumps({"version": web_version, "packages": {"": {"version": web_version}}})
    )
    (root / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## [Unreleased]\n\n## [{web_version}] — 2026-10-02\n\n"
        f"- A compatibility fix.\n\n"
        f"[{web_version}]: https://github.com/eseifert/altero/releases/tag/v{web_version}\n"
    )
    return root


@pytest.mark.parametrize(
    ("python_version", "web_version"),
    [
        ("1.0.0a3", "1.0.0-alpha.3"),
        ("1.0.0b1", "1.0.0-beta.1"),
        ("1.0.0rc1", "1.0.0-rc.1"),
        ("1.0.0", "1.0.0"),
    ],
)
def test_matching_release_can_be_published(
    tmp_path: Path, python_version: str, web_version: str
) -> None:
    root = release_tree(tmp_path, python_version, web_version)
    assert check_release(root, f"v{web_version}") == f"v{web_version}"


def test_a_tag_cannot_publish_another_package_version(tmp_path: Path) -> None:
    root = release_tree(tmp_path, "1.0.0b1", "1.0.0-beta.1")
    with pytest.raises(ValueError, match=r"Tag .* does not match"):
        check_release(root, "v1.0.0")


@pytest.mark.parametrize("name", ["package.json", "package-lock.json"])
def test_a_stale_web_version_blocks_publication(tmp_path: Path, name: str) -> None:
    root = release_tree(tmp_path, "1.0.0b1", "1.0.0-beta.1")
    path = root / "web" / name
    manifest = json.loads(path.read_text())
    manifest["version"] = "1.0.0-alpha.3"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="version does not match"):
        check_release(root)


def test_a_stale_lockfile_root_version_blocks_publication(tmp_path: Path) -> None:
    root = release_tree(tmp_path, "1.0.0b1", "1.0.0-beta.1")
    path = root / "web/package-lock.json"
    manifest = json.loads(path.read_text())
    manifest["packages"][""]["version"] = "1.0.0-alpha.3"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="root package version does not match"):
        check_release(root)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("[1.0.0-beta.1] —", "[1.0.0-alpha.3] —"),
        ("2026-10-02", "2026-02-30"),
        ("- A compatibility fix.", ""),
        ("/tag/v1.0.0-beta.1", "/tag/v1.0.0-alpha.3"),
    ],
)
def test_incomplete_release_notes_block_publication(
    tmp_path: Path, before: str, after: str
) -> None:
    root = release_tree(tmp_path, "1.0.0b1", "1.0.0-beta.1")
    path = root / "CHANGELOG.md"
    path.write_text(path.read_text().replace(before, after))
    with pytest.raises(ValueError, match=r"CHANGELOG\.md"):
        check_release(root)


def test_the_checkout_is_ready_to_tag() -> None:
    root = Path(__file__).resolve().parent.parent
    assert check_release(root).startswith("v")
