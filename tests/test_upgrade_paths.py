"""Upgrade checks must select actual releases and isolate their database/configuration."""

from pathlib import Path

import pytest

from tools.upgrade_corpus import check_preserved
from tools.upgrade_paths import beta_tags, environment, fresh_postgres, matrix


def test_preservation_refuses_lost_data_and_unexpected_versions() -> None:
    before = {
        "/users/1": {
            "version": 10,
            "items": {
                "BKKK2345": {"title": "Keep me", "version": 4},
                "NNTT2345": {"note": "Keep note", "version": 5, "collections": ["AAAA2345"]},
            },
        }
    }
    after: dict = {
        "/users/1": {
            "version": 11,
            "items": {
                "BKKK2345": {"title": "Keep me", "version": 4},
                "NNTT2345": {"note": "Keep note", "version": 11, "collections": []},
            },
        }
    }
    import copy

    check_preserved(before, after)
    for key, field, value in (
        ("BKKK2345", "title", "Lost"),
        ("BKKK2345", "version", 11),
        ("NNTT2345", "note", ""),
        ("NNTT2345", "version", 5),
        ("NNTT2345", "collections", ["AAAA2345"]),
    ):
        broken = copy.deepcopy(after)
        broken["/users/1"]["items"][key][field] = value
        with pytest.raises(AssertionError):
            check_preserved(before, broken)


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


async def test_existing_state_is_never_reused(tmp_path: Path) -> None:
    sentinel = tmp_path / "keep.txt"
    sentinel.write_text("Keep previous evidence")
    with pytest.raises(FileExistsError):
        await matrix(tmp_path, ["v1.0.0-beta.1"], None)
    assert sentinel.read_text() == "Keep previous evidence"


async def test_postgres_option_refuses_another_database_driver(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="postgresql\\+asyncpg"):
        await fresh_postgres(tmp_path, "sqlite+aiosqlite:///important.sqlite")
    assert list(tmp_path.iterdir()) == []


def test_unaffected_library_versions_cannot_move() -> None:
    before = {
        "/users/1": {
            "version": 10,
            "items": {
                "NNTT2345": {"version": 5, "collections": []},
            },
        }
    }
    check_preserved(before, before)
    changed = {
        "/users/1": {
            "version": 11,
            "items": {
                "NNTT2345": {"version": 5, "collections": []},
            },
        }
    }
    with pytest.raises(AssertionError):
        check_preserved(before, changed)
