"""What the instance holds, and what it costs on disk.

An operator running a server has one question the API never had to answer: how
much disk is this, and whose. Upstream cannot answer it honestly — group files
bill to the owner's quota, which is what the forums are full of complaints
about — and altero can, because files are stored once per digest.

So two numbers rather than one. **Nominal** is what each library would cost on
its own, summed: the answer to "what is this group costing us". **Real** is what
is on the disk, counting a file shared between libraries once: the answer to
"what do I have to buy". The difference is what deduplication saves, and it is
reported rather than hidden because an operator planning for growth needs to
know it is there.

Two things that do not add up are reported alongside: bytes on disk nothing
references any more, and attachments whose bytes are not there. The first is
where a self-hosted instance quietly loses disk; the second is what a restore
that lost its files looks like.

Nothing here reads an item. It counts rows and stats files, which is the whole
of what an instance administrator is entitled to — see
:mod:`altero.api.routes.webadmin`.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from altero.models import Collection, Item, ItemField, Library, LibraryType, Tag, User


@dataclass(frozen=True, slots=True)
class LibraryUsage:
    """What one library holds."""

    id: int
    type: LibraryType
    owner_id: int
    name: str
    version: int
    items: int
    trashed: int
    collections: int
    tags: int
    attachments: int
    #: Distinct digests this library references and that are on disk.
    files: int
    #: What those digests weigh. A file shared with another library is counted
    #: here in full and in the other library in full, which is what "what would
    #: this library cost on its own" means.
    bytes: int
    #: Digests it references with no bytes behind them.
    missing: int


@dataclass(frozen=True, slots=True)
class Usage:
    """What the whole instance holds."""

    libraries: list[LibraryUsage] = field(default_factory=list)
    users: int = 0
    groups: int = 0
    #: Sum of every library's own cost. Counts a shared file once per library.
    nominal_bytes: int = 0
    #: What is actually on disk and referenced. Counts a shared file once.
    real_bytes: int = 0
    #: Bytes on disk that no item in any library references.
    orphan_bytes: int = 0
    orphan_files: int = 0
    #: Digests some item claims that are not on disk.
    missing_files: int = 0
    #: Everything in the store, referenced or not.
    stored_files: int = 0
    stored_bytes: int = 0

    @property
    def saved_bytes(self) -> int:
        """What storing files once per digest has saved."""
        return self.nominal_bytes - self.real_bytes


def _is_digest(name: str) -> bool:
    """Whether a file name is one the store would have written."""
    return len(name) == 32 and all(c in "0123456789abcdef" for c in name)


def scan_store(root: Path) -> dict[str, int]:
    """Return the size of every stored file, by digest.

    One walk and one stat per file, because every caller wants all of it. A
    store nobody has uploaded to yet has no directory, which is not an error:
    a fresh instance is exactly that.

    Anything not named like a digest is not part of the store and is passed
    over — a stray note, an editor's backup, whatever an operator left in the
    directory. Counting those as orphans would put somebody else's file on a
    list of things to delete.
    """
    if not root.is_dir():
        return {}

    sizes: dict[str, int] = {}
    for path in root.rglob("*"):
        # Named by digest; see altero.services.storage.file_path.
        if path.is_file() and _is_digest(path.name):
            sizes[path.name] = path.stat().st_size
    return sizes


async def _digests_by_library(session: AsyncSession) -> dict[int, set[str]]:
    """Return the file digests each library references.

    A set per library: a library is charged for bytes, not for attachments, so
    the same file attached to two items in it costs it once.
    """
    rows = await session.execute(
        select(Item.library_id, ItemField.value)
        .join(ItemField, ItemField.item_id == Item.id)
        .where(ItemField.field == "md5", ItemField.value != "")
    )
    digests: dict[int, set[str]] = defaultdict(set)
    for library_id, digest in rows:
        digests[library_id].add(digest)
    return digests


async def _counts(
    session: AsyncSession,
    column: InstrumentedAttribute[int],
    condition: ColumnElement[bool] | None = None,
) -> dict[int, int]:
    """Return a per-library count of whatever ``column``'s table holds."""
    statement = select(column, func.count()).group_by(column)
    if condition is not None:
        statement = statement.where(condition)
    return {library_id: count for library_id, count in await session.execute(statement)}


async def collect(session: AsyncSession, root: Path) -> Usage:
    """Return what the instance holds, as of now.

    Computed on demand rather than kept up to date by the write path. A number
    that is minutes old is fine for the question it answers, and a counter
    maintained on every upload is a thing that can drift from the disk it
    claims to describe — which is exactly the failure this is meant to catch.
    """
    sizes = scan_store(root)
    digests = await _digests_by_library(session)

    items = await _counts(session, Item.library_id)
    trashed = await _counts(session, Item.library_id, Item.deleted.is_(True))
    attachments = await _counts(session, Item.library_id, Item.item_type == "attachment")
    collections = await _counts(session, Collection.library_id)
    tags = await _counts(session, Tag.library_id)

    libraries = list(await session.scalars(select(Library).order_by(Library.id)))

    usage: list[LibraryUsage] = []
    referenced: set[str] = set()
    nominal = 0
    missing_total: set[str] = set()

    for library in libraries:
        held = digests.get(library.id, set())
        present = {digest for digest in held if digest in sizes}
        absent = held - present
        referenced |= present
        missing_total |= absent
        cost = sum(sizes[digest] for digest in present)
        nominal += cost

        usage.append(
            LibraryUsage(
                id=library.id,
                type=library.type,
                owner_id=library.owner_id,
                name=library.name,
                version=library.version,
                items=items.get(library.id, 0),
                trashed=trashed.get(library.id, 0),
                collections=collections.get(library.id, 0),
                tags=tags.get(library.id, 0),
                attachments=attachments.get(library.id, 0),
                files=len(present),
                bytes=cost,
                missing=len(absent),
            )
        )

    orphans = set(sizes) - referenced
    return Usage(
        libraries=usage,
        users=(await session.scalar(select(func.count()).select_from(User))) or 0,
        groups=sum(1 for library in libraries if library.type is LibraryType.GROUP),
        nominal_bytes=nominal,
        real_bytes=sum(sizes[digest] for digest in referenced),
        orphan_bytes=sum(sizes[digest] for digest in orphans),
        orphan_files=len(orphans),
        missing_files=len(missing_total),
        stored_files=len(sizes),
        stored_bytes=sum(sizes.values()),
    )
