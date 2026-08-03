"""Application settings.

Settings come from three places, in increasing order of precedence: the defaults
declared on :class:`Settings`, a ``config.py`` module (see ``config.example.py``),
and ``ALTERO_``-prefixed environment variables.
"""

import importlib.util
import os
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Prefix for environment variables that override settings.
ENV_PREFIX = "ALTERO_"

#: Environment variable holding an alternative path to the configuration module.
CONFIG_PATH_ENV_VAR = f"{ENV_PREFIX}CONFIG"

#: Default location of the configuration module, relative to the repository root.
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.py"


class Settings(BaseSettings):
    """Typed application configuration."""

    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, extra="forbid", frozen=True)

    database_url: str = Field(
        default="sqlite+aiosqlite:///altero.sqlite",
        description="SQLAlchemy database URL. Must use an async driver.",
    )
    host: str = Field(default="127.0.0.1", description="Interface the server binds to.")
    port: int = Field(default=8000, ge=1, le=65535, description="Port the server binds to.")
    debug: bool = Field(default=False, description="Enable debug behaviour and SQL echoing.")
    storage_path: Path = Field(
        default=Path("./storage"),
        description="Directory holding attachment files.",
    )

    smtp_url: str = Field(
        default="",
        description=(
            "Relay for outgoing mail, as smtp://[user:password@]host[:port] or "
            "smtps://... Empty, the default, writes messages to the log "
            "instead, which keeps a fresh instance self-serviceable."
        ),
    )
    mail_from: str = Field(
        default="altero@localhost",
        description="From address on outgoing mail.",
    )
    public_url: str = Field(
        default="",
        description=(
            "Absolute base URL this instance is reached at, used to build "
            "links in email. Empty falls back to the address the request "
            "arrived on, which is right for a single host and wrong behind a "
            "proxy that rewrites it."
        ),
    )

    forwarded_allow_ips: str = Field(
        default="",
        description=(
            "Addresses of proxies whose X-Forwarded-For and X-Forwarded-Proto "
            "may be believed, comma separated, or '*' to believe any peer. "
            "Empty, the default, trusts nothing and reports the address the "
            "connection actually came from. Behind a TLS terminator that is "
            "the terminator, so both the rate limiter and the record of where "
            "a key was last used see one address for everybody until this is "
            "set. Only ever name a proxy that strips the header it forwards; "
            "anything else lets a caller choose the address attributed to it."
        ),
    )

    rate_limit: int = Field(
        default=0,
        ge=0,
        description=(
            "Requests allowed per API key (or per address, unauthenticated) in "
            "each window. Zero disables the limit, which is the default: a "
            "personal instance has nothing to throttle."
        ),
    )
    rate_limit_window: int = Field(
        default=60,
        gt=0,
        description="Length of the rate-limit window, in seconds.",
    )


def _read_config_module(path: Path) -> dict[str, Any]:
    """Return the settings defined by the config module at ``path``.

    Only uppercase module-level names are considered, so imports and helper
    variables inside the config file are ignored. A missing file yields an empty
    mapping, letting a fresh checkout run on the defaults alone.
    """
    if not path.is_file():
        return {}

    spec = importlib.util.spec_from_file_location("altero._config", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ValueError(f"Could not load configuration from {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    known = Settings.model_fields
    values: dict[str, Any] = {}
    for name, value in vars(module).items():
        if not name.isupper() or not name[0].isalpha():
            continue
        field = name.lower()
        if field not in known:
            raise ValueError(f"Unknown setting {name} in {path}")
        values[field] = value
    return values


def _read_environment(environ: Mapping[str, str]) -> dict[str, Any]:
    """Return the settings supplied as ``ALTERO_``-prefixed environment variables.

    Unknown prefixed names are ignored rather than rejected: the environment is a
    shared namespace, and ``ALTERO_CONFIG`` legitimately lives there.
    """
    known = Settings.model_fields
    return {
        field: value
        for name, value in environ.items()
        if name.startswith(ENV_PREFIX) and (field := name[len(ENV_PREFIX) :].lower()) in known
    }


def load_settings(
    config_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Settings:
    """Build a :class:`Settings` instance from the config module and the environment.

    ``config_path`` and ``environ`` are injectable so that tests never depend on
    the developer's own ``config.py`` or shell environment.
    """
    environ = os.environ if environ is None else environ

    if config_path is None:
        configured = environ.get(CONFIG_PATH_ENV_VAR)
        config_path = Path(configured) if configured else DEFAULT_CONFIG_PATH

    # Merge order gives the environment the final say; pydantic coerces the
    # resulting strings to the declared field types.
    values = _read_config_module(config_path) | _read_environment(environ)
    return Settings(**values)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, loading them on first use."""
    return load_settings()
