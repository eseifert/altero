"""Upgrade checks must select actual releases and isolate their database/configuration."""

from pathlib import Path

import pytest

from tools.upgrade_paths import beta_tags, environment


def test_beta_tags_are_complete_ordered_and_exclude_other_releases(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.test",
            "commit",
            "--allow-empty",
            "-m",
            "fixture",
        ],
        check=True,
        capture_output=True,
    )
    for tag in ("v1.0.0-beta.10", "v1.0.0-beta.2", "v1.0.0-beta.1", "v1.0.0-rc.1", "v0.9.0"):
        subprocess.run(["git", "-C", str(tmp_path), "tag", "--no-sign", tag], check=True)
    assert beta_tags(tmp_path) == ["v1.0.0-beta.1", "v1.0.0-beta.2", "v1.0.0-beta.10"]


def test_upgrade_cannot_inherit_an_operators_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALTERO_DATABASE_URL", "sqlite+aiosqlite:///important.sqlite")
    monkeypatch.setenv("ALTERO_CONFIG", "/some/production/config.py")
    monkeypatch.setenv("ALTERO_RETENTION_INTERVAL", "1")
    monkeypatch.setenv("ALTERO_PUBLIC_URL", "https://production.example.test")
    monkeypatch.setenv("PYTHONPATH", "/some/other/source")
    env = environment(tmp_path, tmp_path, "sqlite+aiosqlite:///disposable.sqlite")
    assert env["ALTERO_DATABASE_URL"] == "sqlite+aiosqlite:///disposable.sqlite"
    assert env["ALTERO_CONFIG"] == str(tmp_path / "no-config.py")
    assert env["ALTERO_STORAGE_PATH"] == str(tmp_path / "storage")
    assert "ALTERO_RETENTION_INTERVAL" not in env
    assert "ALTERO_PUBLIC_URL" not in env
    assert env["PYTHONPATH"] == str(tmp_path / "src")
