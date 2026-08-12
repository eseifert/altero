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

# Group notifications. A member of a group library can ask to be told when it
# changes; nobody is subscribed until they do, so an instance where nobody has
# asked sends nothing regardless of these.
#
# The quiet period is how long a library must stop changing before what
# happened in it goes out, which is what turns one sync into one message rather
# than one per batch of fifty. The interval is how often to look; zero turns
# group notifications off entirely, though activity is still recorded.
GROUP_DIGEST_QUIET_PERIOD = 900
GROUP_DIGEST_INTERVAL = 60

# Retention: how long the server keeps what nobody asked it to keep. Zero is
# never, which is the default for the first two — an instance that started
# deleting somebody's trash because it was upgraded would be the worst kind of
# surprise. zotero.org empties the trash after 30 days, if matching it is what
# you want. An administrator can change these three in the browser, and a value
# set there wins over the value here.
#
# The interval is how often to apply them; zero, the default, means only
# `altero retention run` ever does. Age is measured from the last time the
# server saw the object change — see docs/administration.md#retention.
TRASH_RETENTION_DAYS = 0
ACTIVITY_RETENTION_DAYS = 0
UPLOAD_RETENTION_HOURS = 24
RETENTION_INTERVAL = 0

# Whether anybody may register an account from the browser. The first account
# is always allowed, so a fresh instance is reachable without shell access, and
# so is anyone holding an unanswered invitation to a group. Everything else is
# `altero user add`.
OPEN_REGISTRATION = False

# Whether somebody who has forgotten their password may ask for a link to set a
# new one. Off by default: it makes the mail relay part of the authentication,
# so whoever can read the mailbox can take the account. Does nothing without
# SMTP_URL above — a link that sets a password, written to the log, is one
# anybody who can read the log can follow — and nothing for an account whose
# address was never confirmed. An administrator can issue the same link from
# Administration → Accounts whatever this says.
PASSWORD_RESET = False
