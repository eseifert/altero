"""Example configuration for altero.

Copy this file to ``config.py`` and adjust the values. ``config.py`` is ignored by
git, so local settings never end up in the repository.

Every setting can also be supplied as an ``ALTERO_``-prefixed environment variable
(for example ``ALTERO_PORT=9000``), which takes precedence over this file. Point
``ALTERO_CONFIG`` at another path to load a different configuration module.
"""

# SQLAlchemy database URL. The driver must be an asynchronous one.
DATABASE_URL = "sqlite+aiosqlite:///altero.sqlite"

# Interface and port the server binds to.
HOST = "127.0.0.1"
PORT = 8000

# Enable debug behaviour, SQL echoing and auto-reload. Never enable in production.
DEBUG = False

# Directory holding attachment files.
STORAGE_PATH = "./storage"
