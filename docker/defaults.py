"""The container image's own configuration, installed as /app/config.py.

Only what the image needs to start without Compose. The environment outranks
everything here, which is how docker/compose.yaml points altero at PostgreSQL,
and a config.py mounted over this file replaces it whole.
"""

# On the /data volume, beside the attachments. altero's own default is a path
# relative to the working directory, /app, where the image's unprivileged user
# cannot write.
DATABASE_URL = "sqlite+aiosqlite:////data/altero.sqlite"
