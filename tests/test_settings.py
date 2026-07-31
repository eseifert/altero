"""Tests for configuration loading."""

from pathlib import Path

import pytest

from altero.settings import Settings, load_settings


def test_defaults_apply_without_a_config_file(tmp_path: Path) -> None:
    settings = load_settings(config_path=tmp_path / "missing.py", environ={})

    assert settings.database_url == "sqlite+aiosqlite:///altero.sqlite"
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.debug is False


def test_config_file_overrides_defaults(tmp_path: Path) -> None:
    config = tmp_path / "config.py"
    config.write_text(
        'DATABASE_URL = "sqlite+aiosqlite:///custom.sqlite"\nPORT = 9000\nDEBUG = True\n'
    )

    settings = load_settings(config_path=config, environ={})

    assert settings.database_url == "sqlite+aiosqlite:///custom.sqlite"
    assert settings.port == 9000
    assert settings.debug is True


def test_config_file_ignores_private_and_lowercase_names(tmp_path: Path) -> None:
    config = tmp_path / "config.py"
    config.write_text('import os\n\n_SECRET = "x"\nport = 1234\nPORT = 9000\n')

    settings = load_settings(config_path=config, environ={})

    assert settings.port == 9000


def test_environment_overrides_the_config_file(tmp_path: Path) -> None:
    config = tmp_path / "config.py"
    config.write_text("PORT = 9000\n")

    settings = load_settings(config_path=config, environ={"ALTERO_PORT": "9500"})

    assert settings.port == 9500


def test_unknown_config_keys_are_rejected(tmp_path: Path) -> None:
    config = tmp_path / "config.py"
    config.write_text('NOT_A_SETTING = "surprise"\n')

    with pytest.raises(ValueError, match="NOT_A_SETTING"):
        load_settings(config_path=config, environ={})


def test_settings_can_be_built_directly() -> None:
    settings = Settings(port=1234)

    assert settings.port == 1234
