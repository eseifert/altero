"""Bringing a store written by an earlier altero to the current layout.

Until revision ``e5b8c1f07a26`` a snapshot ZIP was stored under the digest of
the file inside it, and a file restored from an archive under whatever digest
the archive gave it. Now every file is named by the digest of its own bytes
(see :mod:`altero.services.storage`), so a store from before has to be
renamed once: each registered file is hashed, and one whose name is not its
digest is linked under its digest, the attachments registered to it moved
over -- recording that a ZIP around another file is one -- and only then is
the old name removed.

Done when the server starts rather than in the migration, because only the
server knows where its store is: `alembic upgrade` may run from anywhere, and
a migration that looked in the wrong directory would find nothing to do and
say so. A marker in the store records that it is done; a lock keeps two
workers starting together from doing it twice. Run again after being cut off
part way, it picks up where it stopped: a file already linked is not linked
again, and an old name is removed only once nothing is registered to it.
"""

import asyncio
import fcntl
import hashlib
import logging
import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Item
from altero.services.storage import file_path, is_file_digest, starts_like_zip

logger = logging.getLogger("altero.storelayout")

#: The layout the store is in once this has run.
LAYOUT = "2"

#: Where the store says which layout it is in. Not a digest, so every walk of
#: the store passes it over, and not `storage.STAGING_PREFIX`, which the sweep
#: of abandoned writes would take for one.
MARKER = "altero-layout"

#: Held while the store is renamed.
LOCK = "altero-layout.lock"


async def ensure_current(session: AsyncSession, root: Path) -> int:
    """Bring the store at ``root`` to the current layout. Returns how many files moved."""
    if await asyncio.to_thread(_is_current, root):
        return 0
    await asyncio.to_thread(root.mkdir, parents=True, exist_ok=True)
    with _locked(root):
        # Asked again: another worker may have finished while this one waited.
        if await asyncio.to_thread(_is_current, root):
            return 0
        moved = await _rename(session, root)
        await asyncio.to_thread(_mark, root)
    if moved:
        logger.info("Renamed %d stored files to the digest of their own bytes", moved)
    return moved


def _is_current(root: Path) -> bool:
    try:
        return (root / MARKER).read_text().strip() == LAYOUT
    except OSError:
        return False


@contextmanager
def _locked(root: Path) -> Iterator[None]:
    with (root / LOCK).open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _mark(root: Path) -> None:
    staged = root / f"{MARKER}.new"
    staged.write_text(f"{LAYOUT}\n")
    os.replace(staged, root / MARKER)


async def _rename(session: AsyncSession, root: Path) -> int:
    names = [
        name
        for name in await session.scalars(
            select(Item.registered_md5).where(Item.registered_md5.is_not(None)).distinct()
        )
        if name is not None
    ]
    moved: list[Path] = []
    for name in names:
        if not is_file_digest(name):
            continue
        found = await asyncio.to_thread(_content_name, root, name)
        if found is None:
            continue
        digest, wrapped = found
        await session.execute(
            update(Item)
            .where(Item.registered_md5 == name)
            .values(registered_md5=digest, registered_zip=wrapped)
        )
        moved.append(file_path(root, name))
    await session.commit()
    # Only now: until the rows name the new file, the old name is what serves it.
    for path in moved:
        path.unlink(missing_ok=True)
    return len(moved)


def _content_name(root: Path, name: str) -> tuple[str, bool] | None:
    """Link the file stored as ``name`` under its own digest, if that is another name.

    Returns that digest and whether the file is a ZIP around the attachment's
    file -- which a ZIP stored under another digest than its own always was:
    an upload checks a plain file against the name it is given -- or ``None``
    where there is nothing to move.
    """
    path = file_path(root, name)
    if not path.is_file():
        return None
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    own = digest.hexdigest()
    if own == name:
        return None
    target = file_path(root, own)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(path, target)
        except OSError:
            # A mount that will not make hard links: a copy, put in place whole.
            staged = target.with_name(f".altero-{own}")
            shutil.copyfile(path, staged)
            os.replace(staged, target)
    return own, starts_like_zip(path)
