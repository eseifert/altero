"""The configuration the container image ships as its ``config.py``.

A misspelled name there would stop every container that has no Compose file
around it, so it is loaded here the way the image loads it.
"""

from pathlib import Path

from altero.settings import load_settings

DEFAULTS = Path(__file__).resolve().parents[1] / "docker" / "defaults.py"


def test_the_database_lives_on_the_data_volume() -> None:
    settings = load_settings(config_path=DEFAULTS, environ={})

    assert settings.database_url == "sqlite+aiosqlite:////data/altero.sqlite"


def test_the_environment_still_chooses_the_database() -> None:
    url = "postgresql+asyncpg://altero:altero@db:5432/altero"

    settings = load_settings(config_path=DEFAULTS, environ={"ALTERO_DATABASE_URL": url})

    assert settings.database_url == url
