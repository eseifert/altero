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

# Requests allowed per API key, or per address when unauthenticated, in each
# window. Zero disables the limit. A caller over it gets 429 with Retry-After.
RATE_LIMIT = 0
RATE_LIMIT_WINDOW = 60

# Relay for outgoing mail — confirmations, group invitations and security
# notices — as smtp://[user:password@]host[:port] or smtps://... Credentials
# are percent-encoded, so an address as the username is `ada%40example.org`.
# Empty writes the messages to the log instead, which is how a fresh instance
# with no relay stays self-serviceable. See docs/email.md.
SMTP_URL = ""

# From address on outgoing mail. Set it to something the relay will send as.
MAIL_FROM = "altero@localhost"

# Absolute base URL this instance is reached at, used to build the links in
# email. Empty falls back to the address the request arrived on, which is right
# for a single host and wrong behind a proxy that rewrites it.
PUBLIC_URL = ""

# Whether anybody may register an account from the browser. The first account
# is always allowed, so a fresh instance is reachable without shell access, and
# so is anyone holding an unanswered invitation to a group. Everything else is
# `altero user add`.
OPEN_REGISTRATION = False
