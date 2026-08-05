#!/bin/sh
# Bring the database up to date before serving. Running this on every start,
# rather than as a step someone has to remember, is what makes an upgrade
# `git pull && docker compose up -d --build` and nothing else.
#
# Copied into the image as altero-entrypoint.sh; see docker/Dockerfile.
#
# Alembic is idempotent: on an unchanged database this is a no-op, and if it
# fails the container exits instead of serving against a schema it does not
# understand.
set -eu

if [ "${ALTERO_SKIP_MIGRATIONS:-}" != "1" ]; then
    alembic upgrade head
fi

exec "$@"
