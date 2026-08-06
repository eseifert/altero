"""Copying a library in from zotero.org, from the browser.

The fourth and last thing the interface writes to a library, and the largest:
it replaces the whole of one. So it is held to the same rules the restore in
``webtransfer.py`` is, which does the same thing from a file --

- the owner of the personal library and nobody else;
- the account password again, because a session cookie is what somebody who
  borrowed an unlocked laptop already has;
- ``replace`` before a library with anything in it is touched.

-- and it ends in exactly that restore. Everything between here and
:func:`altero.services.transfer.import_library` is a download.

What is different is the waiting. Reading a few thousand items out of somebody
else's server is minutes, so the request starts the work and answers, and the
page polls. That makes this the one endpoint whose effect outlives its request,
and the reason for :mod:`altero.services.migrations`.

The API key is used and dropped. It is never written to the database, never
logged, and lives only in the running migration's closure -- long enough to read
the library and no longer.
"""

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Body
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from altero.api.deps import SessionDep
from altero.api.routes.web import CsrfDep, CurrentUserDep
from altero.errors import AlteroError, ForbiddenError, InvalidInputError
from altero.models import LibraryType, User
from altero.services import account, auth, migrations, transfer, zoteroapi, zoteroimport

router = APIRouter(prefix="/web", tags=["web"])

#: How long to wait on api.zotero.org. Generous on reads because a page of a
#: hundred items with their notes is not small, and a file may be a book.
TIMEOUT = httpx.Timeout(60.0, read=300.0)


class StartMigration(BaseModel):
    """What starting one takes."""

    api_key: str = Field(alias="apiKey")
    current_password: str = Field(alias="currentPassword")
    #: Discard what the library already holds. Without it, a library with
    #: anything in it is refused rather than merged.
    replace: bool = False
    #: Where to read from. Not offered by the interface -- it is here so that a
    #: test, or somebody moving between two altero instances, can point it
    #: somewhere else.
    server: str = zoteroapi.DEFAULT_BASE_URL


async def _run(
    *,
    sessions: async_sessionmaker[Any],
    migration: migrations.Migration,
    key: str,
    server: str,
    user_id: int,
    storage_root: Path,
    replace: bool,
) -> None:
    """Read the library, restore it, and record how it went.

    Its own session rather than the request's: the request has answered and its
    session is closed. Its own workspace too, removed whatever happens -- an
    archive is as large as the library, and a failure is not a reason to leave
    that on the disk.
    """
    workspace = Path(tempfile.mkdtemp(prefix="altero-migrate-"))
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            api = zoteroapi.ZoteroApi(
                key=key,
                client=client,
                base_url=server,
                on_wait=lambda seconds: migration.observe(
                    zoteroimport.Progress(
                        stage=migration.stage,
                        done=migration.done,
                        total=migration.total,
                        detail=f"waiting {int(seconds)}s for zotero.org",
                    )
                ),
            )
            summary = await zoteroimport.fetch_archive(
                api,
                destination=workspace / "zotero.zip",
                target_user_id=user_id,
                report=migration.observe,
            )

        migration.summary = summary
        migration.observe(zoteroimport.Progress(stage="restoring"))

        async with sessions() as session:
            library = await auth.get_library(session, LibraryType.USER, user_id)
            await transfer.import_library(
                session,
                archive=workspace / "zotero.zip",
                storage_root=storage_root,
                replace=replace,
                into=library,
            )
            await session.commit()

        migrations.register.finish(migration)
    except AlteroError as thrown:
        migrations.register.finish(migration, error=thrown.message)
    except Exception as thrown:  # pragma: no cover - defensive
        migrations.register.finish(migration, error=str(thrown) or thrown.__class__.__name__)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def _own_library(user: User, user_id: int) -> None:
    if user.id != user_id:
        raise ForbiddenError("That is not your library")


@router.get("/migrate/zotero")
async def migration_status(user: CurrentUserDep) -> Response:
    """Report the migration this account has running, or the last one it ran.

    ``null`` when there is none. A restart forgets them, which is worth knowing
    when reading this: it means "this process has no record", not "nothing
    happened" -- what a migration did is in the library either way.
    """
    migration = migrations.register.get(user.id)
    return JSONResponse(migration.render() if migration is not None else None)


@router.post("/migrate/zotero", status_code=202)
async def start_migration(
    request: Request,
    session: SessionDep,
    user: CurrentUserDep,
    _csrf: CsrfDep,
    body: Annotated[StartMigration, Body()],
) -> Response:
    """Begin copying this account's zotero.org library into its own.

    Answers ``202`` as soon as the work has started, with the same body
    ``GET`` returns, so the page can show the first stage without a second
    request.
    """
    _own_library(user, user.id)
    account.require_password(user, body.current_password)

    key = body.api_key.strip()
    if not key:
        raise InvalidInputError("An API key is required")

    library = await auth.get_library(session, LibraryType.USER, user.id)
    if not body.replace and not await transfer.is_empty(session, library):
        # Refused here rather than after several minutes of downloading, which
        # is where `import_library` would refuse it.
        raise InvalidInputError(
            "This library already holds objects. Choose to replace them to continue."
        )

    migration = migrations.register.start(user.id)
    # The register holds the task, which is what keeps it from being collected
    # while it runs -- asyncio keeps only a weak reference of its own. Nothing
    # awaits it: the point of this endpoint is that it answers first.
    migration.task = asyncio.create_task(
        _run(
            sessions=request.app.state.database.session_factory,
            migration=migration,
            key=key,
            server=body.server,
            user_id=user.id,
            storage_root=Path(request.app.state.settings.storage_path),
            replace=body.replace,
        ),
        name=f"altero.migrate.{user.id}",
    )

    return JSONResponse(migration.render(), status_code=202)
