"""Inspect the files that will be distributed, rather than just build configuration."""

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from tools.release import check_artifacts

VERSION = "1.0.0b1"
TAG = "v1.0.0-beta.1"
INDEX = "altero/web/static/index.html"
SCRIPT = "altero/web/static/assets/index-example.js"


def artifacts(
    root: Path,
    *,
    missing_wheel: str = "",
    missing_source: str = "",
    extra_source: str = "",
    different_script: bool = False,
    metadata_version: str = VERSION,
) -> Path:
    files = {
        INDEX: b'<script type="module" src="/app/assets/index-example.js"></script>',
        SCRIPT: b"console.log('application')",
    }
    with zipfile.ZipFile(root / f"altero-{VERSION}-py3-none-any.whl", "w") as wheel:
        wheel.writestr(f"altero-{VERSION}.dist-info/METADATA", f"Version: {metadata_version}\n")
        for name, content in files.items():
            if name != missing_wheel:
                wheel.writestr(name, content)
    source_files = {f"src/{name}": content for name, content in files.items()}
    if different_script:
        source_files[f"src/{SCRIPT}"] = b"console.log('stale application')"
    if extra_source:
        source_files[extra_source] = b"Unrelated local work"
    with tarfile.open(root / f"altero-{VERSION}.tar.gz", "w:gz") as source:
        for name, content in source_files.items():
            if name == missing_source:
                continue
            member = tarfile.TarInfo(f"altero-{VERSION}/{name}")
            member.size = len(content)
            source.addfile(member, io.BytesIO(content))
    return root


def test_complete_browser_artifacts_can_be_distributed(tmp_path: Path) -> None:
    check_artifacts(artifacts(tmp_path), TAG)


def test_a_wheel_without_the_browser_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="missing the built browser interface"):
        check_artifacts(artifacts(tmp_path, missing_wheel=INDEX), TAG)


def test_a_browser_index_with_a_missing_script_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="references missing asset"):
        check_artifacts(artifacts(tmp_path, missing_wheel=SCRIPT), TAG)


def test_a_source_archive_that_cannot_rebuild_the_browser_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Source archive is missing browser asset"):
        check_artifacts(artifacts(tmp_path, missing_source=f"src/{SCRIPT}"), TAG)


def test_unrelated_workspace_files_cannot_be_distributed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="includes unexpected file"):
        check_artifacts(artifacts(tmp_path, extra_source="private-notes.md"), TAG)


def test_the_source_archive_and_wheel_cannot_carry_different_browser_builds(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="differs from wheel"):
        check_artifacts(artifacts(tmp_path, different_script=True), TAG)


def test_the_distributed_version_must_match_the_tag(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="metadata does not match"):
        check_artifacts(artifacts(tmp_path, metadata_version="1.0.0a3"), TAG)
