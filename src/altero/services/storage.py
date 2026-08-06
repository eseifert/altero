"""The attachment file protocol.

Uploading a file takes three requests: the client asks permission and declares
what it is about to send, sends the bytes, then tells the server they arrived.
The upstream server hands out an S3 URL for the middle step; altero has no S3, so
it takes the bytes itself and the authorization step points back at this server.

Files are stored under their MD5 rather than their name, so the same file
attached twice is stored once, and a client that already knows the digest can be
told the upload is unnecessary.
"""

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import (
    InvalidInputError,
    NotFoundError,
    PreconditionFailedError,
    PreconditionRequiredError,
)
from altero.keys import generate_api_key
from altero.models import Item, ItemField, Library, StorageUpload

#: Fields an attachment carries once a file is attached to it.
FILE_FIELDS = ("filename", "md5", "mtime", "contentType", "charset")


def file_digest(body: bytes) -> str:
    """Return the digest a file is stored under."""
    return hashlib.md5(body, usedforsecurity=False).hexdigest()


def file_path(root: Path, md5: str) -> Path:
    """Return where the bytes with this digest live.

    Fanned out by the first two characters so one directory does not end up
    holding every file in the library.
    """
    return root / md5[:2] / md5


def _require_attachment(item: Item) -> None:
    if item.item_type != "attachment":
        raise InvalidInputError("File uploads are only valid for attachments")


def current_md5(item: Item) -> str | None:
    """Return the digest of the file currently attached, if there is one."""
    return item.field_values().get("md5") or None


def check_preconditions(item: Item, if_match: str | None, if_none_match: str | None) -> None:
    """Fail unless the file the client believes is attached is the one that is.

    ``If-None-Match: *`` means "only if there is no file yet"; ``If-Match``
    names the digest being replaced. One or the other is required, so a client
    working from stale information cannot overwrite a newer file.
    """
    existing = current_md5(item)

    if if_none_match is not None:
        if if_none_match != "*":
            raise InvalidInputError("Only If-None-Match: * is supported")
        if existing is not None:
            raise PreconditionFailedError("If-None-Match: * set but file exists")
        return

    if if_match is not None:
        if existing != if_match:
            raise PreconditionFailedError("If-Match set but file does not match")
        return

    raise PreconditionRequiredError("If-Match or If-None-Match must be provided")


def parse_authorization(form: dict[str, str]) -> dict[str, Any]:
    """Read and check what the client says it is about to upload."""
    missing = [name for name in ("md5", "filename", "filesize", "mtime") if not form.get(name)]
    if missing:
        raise InvalidInputError(f"{missing[0]} not provided")

    md5 = form["md5"]
    if len(md5) != 32 or not all(c in "0123456789abcdef" for c in md5.lower()):
        raise InvalidInputError(f"Invalid md5 '{md5}'")

    try:
        filesize = int(form["filesize"])
        mtime = int(form["mtime"])
    except ValueError:
        raise InvalidInputError("Invalid filesize or mtime") from None
    if filesize < 0:
        raise InvalidInputError("Invalid filesize")

    # A snapshot is uploaded as a ZIP. `md5` then describes the original file
    # while the bytes on the wire are the archive, so the transfer has to be
    # checked against `zipMD5`; `filesize` already refers to the archive.
    zip_md5 = (form.get("zipMD5") or "").lower() or None
    if zip_md5 and len(zip_md5) != 32:
        raise InvalidInputError(f"Invalid zipMD5 '{zip_md5}'")

    return {
        "md5": md5.lower(),
        "filename": form["filename"],
        "filesize": filesize,
        "mtime": mtime,
        "content_type": form.get("contentType", ""),
        "charset": form.get("charset", ""),
        "zip_md5": zip_md5,
        "zip_filename": form.get("zipFilename", ""),
    }


async def authorize(
    session: AsyncSession,
    library: Library,
    item: Item,
    declared: dict[str, Any],
    root: Path,
    base_url: str = "",
) -> dict[str, Any]:
    """Authorize an upload, or report that the bytes are already held.

    Returns either ``{"exists": 1}`` or the instructions for sending the file.
    """
    _require_attachment(item)

    if file_path(root, declared["md5"]).is_file():
        # Someone has already uploaded these exact bytes, so only the metadata
        # needs attaching.
        await attach(session, item, declared)
        return {"exists": 1}

    upload = StorageUpload(
        key=generate_api_key(),
        item_id=item.id,
        library_id=library.id,
        md5=declared["md5"],
        zip_md5=declared.get("zip_md5"),
        filename=declared["filename"],
        filesize=declared["filesize"],
        mtime=declared["mtime"],
        content_type=declared["content_type"],
        charset=declared["charset"],
    )
    session.add(upload)
    await session.flush()

    return {
        # Absolute: the client hands this straight to XMLHttpRequest.open(),
        # which rejects a bare path.
        "url": f"{base_url}/storage/upload/{upload.key}",
        "contentType": declared["content_type"] or "application/octet-stream",
        # Upstream fills these with the S3 form envelope. There is none here, so
        # the client sends the file with nothing wrapped around it.
        "prefix": "",
        "suffix": "",
        "uploadKey": upload.key,
    }


async def get_upload(session: AsyncSession, key: str) -> StorageUpload:
    """Return an authorized upload by its key."""
    upload = await session.get(StorageUpload, key)
    if upload is None:
        raise NotFoundError("Upload not found")
    return upload


def store_bytes(root: Path, upload: StorageUpload, body: bytes) -> None:
    """Write the uploaded bytes, checking they are what was promised.

    A digest that does not match means the transfer went wrong or the client
    described a different file; either way storing it would leave the attachment
    pointing at contents nobody expects.
    """
    if len(body) != upload.filesize:
        raise InvalidInputError(
            f"Uploaded file has wrong size (expected {upload.filesize}, got {len(body)})"
        )

    # For a zipped upload the bytes are the archive, so they are checked
    # against its digest; `md5` still identifies the original file.
    expected = upload.zip_md5 or upload.md5
    digest = hashlib.md5(body, usedforsecurity=False).hexdigest()
    if digest != expected:
        raise InvalidInputError(f"Uploaded file has wrong md5 (expected {expected})")

    path = file_path(root, upload.md5)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


async def attach(session: AsyncSession, item: Item, declared: dict[str, Any]) -> None:
    """Record on the item which file is now attached to it."""
    values = {
        "filename": declared["filename"],
        "md5": declared["md5"],
        "mtime": str(declared["mtime"]),
        "contentType": declared["content_type"],
        "charset": declared["charset"],
    }
    existing = {field.field: field for field in item.fields}
    for name, value in values.items():
        if not value and name in ("contentType", "charset"):
            continue
        if name in existing:
            existing[name].value = value
        else:
            item.fields.append(ItemField(field=name, value=value))
    await session.flush()


async def register(
    session: AsyncSession,
    item: Item,
    upload: StorageUpload,
    version: int,
) -> None:
    """Complete an upload, attaching the file to the item."""
    if not upload.received:
        raise InvalidInputError("Upload has not been received")
    if upload.item_id != item.id:
        raise InvalidInputError("Upload does not belong to this item")

    await attach(
        session,
        item,
        {
            "md5": upload.md5,
            "filename": upload.filename,
            "mtime": upload.mtime,
            "content_type": upload.content_type,
            "charset": upload.charset,
        },
    )
    item.version = version
    await session.delete(upload)


async def stored_file(item: Item, root: Path) -> tuple[Path, dict[str, str]]:
    """Return the path of the file attached to ``item`` and its metadata."""
    fields = item.field_values()
    md5 = fields.get("md5")
    if not md5:
        raise NotFoundError("Not found")

    path = file_path(root, md5)
    if not path.is_file():
        # The row says there is a file but the bytes are gone.
        raise NotFoundError("Not found")
    return path, fields


#: What every ZIP archive starts with.
_ZIP_MAGIC = b"PK\x03\x04"


@lru_cache(maxsize=1024)
def _digest_of(path: Path, size: int, modified: int) -> str:
    """Return the digest of the bytes at ``path``.

    ``size`` and ``modified`` are not read: they are part of the cache key, so
    that a file replaced on disk is hashed again rather than answered from a
    stale entry.
    """
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def is_compressed(path: Path, md5: str) -> bool:
    """Whether the stored bytes are an archive wrapping the file the item names.

    The client zips a snapshot before uploading it, and a snapshot migrated out
    of zotero.org arrives the same way. ``md5`` then describes the
    file *inside* the archive rather than the bytes on the wire, and the client
    has to be told so on download: given ``Zotero-File-Compressed: No`` it
    writes the archive itself to disk under the attachment's name.

    Nothing records which of the two a stored file is. It does not have to: the
    store is addressed by the digest the item claims, so a wrapper is exactly a
    file whose own digest is not the name it is stored under. The magic number
    is checked first, so only archives are ever hashed -- a .docx or .epub
    attachment is one too, and is told apart from a wrapper by hashing to the
    digest the item claims.
    """
    with path.open("rb") as handle:
        if handle.read(len(_ZIP_MAGIC)) != _ZIP_MAGIC:
            return False

    stat = path.stat()
    return _digest_of(path, stat.st_size, stat.st_mtime_ns) != md5


async def purge_stale_uploads(session: AsyncSession, before: Any) -> int:
    """Delete authorizations whose bytes never arrived. Returns how many."""
    stale = list(
        await session.scalars(
            select(StorageUpload).where(
                StorageUpload.received.is_(False), StorageUpload.created < before
            )
        )
    )
    for upload in stale:
        await session.delete(upload)
    return len(stale)
