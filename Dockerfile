# One process, one database, one directory of attachments. Nothing here should
# need explaining to whoever has to upgrade it at two in the morning.
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

# Dependencies first, from the lock file alone, so editing the source does not
# reinstall them. --frozen fails rather than silently resolving something the
# lock file does not describe.
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev --extra postgres

# README.md comes along because pyproject.toml declares it as the package
# readme, and the build fails without it.
COPY alembic.ini README.md ./
COPY migrations ./migrations
COPY src ./src
RUN uv sync --frozen --no-dev --extra postgres

# Attachments and, for a single-user SQLite deployment, the database itself.
# Declared so that neither is lost with the container.
VOLUME /data
ENV ALTERO_STORAGE_PATH=/data/storage \
    ALTERO_HOST=0.0.0.0 \
    ALTERO_PORT=8000 \
    PATH="/app/.venv/bin:$PATH"

# Nothing here needs root, and a stray upload should not be able to write
# anywhere but /data.
RUN useradd --system --uid 10001 altero \
    && mkdir -p /data/storage \
    && chown -R altero:altero /data
USER altero

EXPOSE 8000

# The readiness probe an orchestrator polls; it opens a database connection, so
# a container that cannot reach its database reports unhealthy rather than
# accepting traffic it can only fail.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

COPY docker-entrypoint.sh /usr/local/bin/
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["altero"]
