"""Saved search endpoints."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import Response

from altero import atom, serializers
from altero.api.batch import batch_write
from altero.api.deps import (
    AccessDep,
    BaseUrlDep,
    ReadableLibraryDep,
    SessionDep,
    WritableLibraryDep,
)
from altero.api.responses import (
    AtomFeed,
    entry_response,
    library_headers,
    listing_response,
    not_modified,
    object_response,
)
from altero.errors import InvalidInputError, RequestTooLargeError
from altero.models import Library, SavedSearch
from altero.query import (
    NAMED_SORT_FIELDS,
    OBJECT_FORMATS,
    SINGLE_NAMED_FORMATS,
    Format,
    ListQuery,
    parse_list_query,
)
from altero.services import auth, writes
from altero.services import objectwrites as object_writes
from altero.services import searches as searches_service

router = APIRouter(tags=["searches"])


def search_query(request: Request, formats: frozenset[Format] = OBJECT_FORMATS) -> ListQuery:
    return parse_list_query(
        list(request.query_params.multi_items()),
        sort_fields=NAMED_SORT_FIELDS,
        default_sort="title",
        formats=formats,
    )


def _timestamps(obj: SavedSearch) -> tuple[str, str]:
    """Return a saved search's ``published`` and ``updated``.

    Off the stored row, because the JSON envelope of a saved search carries no
    timestamps -- the same reason the collection routes read theirs there.
    """
    return serializers.timestamp(obj.date_added), serializers.timestamp(obj.date_modified)


@router.get("/users/{user_id}/searches")
@router.get("/groups/{group_id}/searches")
async def list_searches(
    request: Request, session: SessionDep, library: ReadableLibraryDep, base_url: BaseUrlDep
) -> Response:
    query = search_query(request)
    if (response := not_modified(request, library.version)) is not None:
        return response

    page = await searches_service.list_searches(session, library, query)

    envelopes = [serializers.saved_search(search, library, base_url) for search in page.objects]
    objects: list[Any] = []
    feed: AtomFeed | None = None

    if query.response_format is Format.JSON:
        objects = envelopes
    elif query.response_format is Format.ATOM:
        feed = AtomFeed(
            describes="Searches",
            author=atom.author_for(library, base_url),
            entries=tuple(
                atom.search_entry(envelope, query.content, timestamps=_timestamps(search))
                for envelope, search in zip(envelopes, page.objects, strict=True)
            ),
            empty_updated=serializers.timestamp(datetime.now(UTC).replace(tzinfo=None)),
        )

    return listing_response(
        request,
        query,
        version=page.library_version,
        total=page.total,
        objects=objects,
        keys=[search.key for search in page.objects],
        versions={search.key: search.version for search in page.objects},
        feed=feed,
    )


@router.get("/users/{user_id}/searches/{search_key}")
@router.get("/groups/{group_id}/searches/{search_key}")
async def get_search(
    search_key: str,
    request: Request,
    session: SessionDep,
    library: ReadableLibraryDep,
    base_url: BaseUrlDep,
) -> Response:
    query = search_query(request, SINGLE_NAMED_FORMATS)
    if (response := not_modified(request, library.version)) is not None:
        return response

    search = await searches_service.get_search(session, library, search_key)
    envelope = serializers.saved_search(search, library, base_url)

    if query.response_format is Format.ATOM:
        return entry_response(
            atom.search_entry(envelope, query.content, timestamps=_timestamps(search)),
            atom.author_for(library, base_url),
            library.version,
        )

    return object_response(envelope, library.version)


@router.post("/users/{user_id}/searches")
@router.post("/groups/{group_id}/searches")
async def create_searches(
    request: Request,
    session: SessionDep,
    library: WritableLibraryDep,
    access: AccessDep,
    base_url: BaseUrlDep,
) -> Response:
    """Create or update a batch of saved searches.

    Each object is a diff against what is stored, for the reason the collection
    batch gives: the client uploads only what it changed, so a search sent to
    the trash arrives as ``{key, version, deleted}``. A new search still has to
    carry its name and its conditions.
    """

    async def save(
        session: AsyncSession, library: Library, payload: dict[str, Any], version: int
    ) -> dict[str, Any] | None:
        search = await object_writes.save_search(
            session,
            library,
            payload,
            version,
            detect_unchanged=True,
            replace=False,
            permit=access,
        )
        if search is None:
            return None
        return serializers.saved_search(search, library, base_url)

    return await batch_write(request, session, library, save)


@router.put("/users/{user_id}/searches/{search_key}")
@router.put("/groups/{group_id}/searches/{search_key}")
async def replace_search(
    search_key: str,
    request: Request,
    session: SessionDep,
    library: WritableLibraryDep,
    access: AccessDep,
) -> Response:
    """Replace one saved search. Properties left out are cleared."""
    return await _write_single(search_key, request, session, library, access, replace=True)


@router.patch("/users/{user_id}/searches/{search_key}")
@router.patch("/groups/{group_id}/searches/{search_key}")
async def update_search(
    search_key: str,
    request: Request,
    session: SessionDep,
    library: WritableLibraryDep,
    access: AccessDep,
) -> Response:
    """Update one saved search in place. Properties left out are untouched."""
    return await _write_single(search_key, request, session, library, access, replace=False)


async def _write_single(
    search_key: str,
    request: Request,
    session: AsyncSession,
    library: Library,
    access: auth.Access,
    *,
    replace: bool,
) -> Response:
    payload = await request.json()
    if not isinstance(payload, dict):
        raise InvalidInputError("Uploaded data must be a JSON object")

    header_version = writes.parse_version_header(request.headers.get("If-Unmodified-Since-Version"))
    if header_version is not None:
        payload = {"version": header_version, **payload}

    version = await writes.bump_library_version(session, library)
    await object_writes.save_search(
        session,
        library,
        payload,
        version,
        key=search_key,
        replace=replace,
        require_version=True,
        permit=access,
    )
    await session.commit()

    return Response(status_code=204, headers=library_headers(version))


@router.delete("/users/{user_id}/searches/{search_key}")
@router.delete("/groups/{group_id}/searches/{search_key}")
async def delete_search(
    search_key: str,
    request: Request,
    session: SessionDep,
    library: WritableLibraryDep,
    access: AccessDep,
) -> Response:
    """Remove one saved search."""
    library = await writes.lock_library(session, library)
    expected = writes.parse_version_header(request.headers.get("If-Unmodified-Since-Version"))
    writes.check_library_version(library, expected, required=True)

    await searches_service.get_search(session, library, search_key)
    version = await writes.bump_library_version(session, library)
    await object_writes.delete_searches(session, library, [search_key], version, permit=access)
    await session.commit()

    return Response(status_code=204, headers=library_headers(version))


@router.delete("/users/{user_id}/searches")
@router.delete("/groups/{group_id}/searches")
async def delete_searches(
    request: Request,
    session: SessionDep,
    library: WritableLibraryDep,
    access: AccessDep,
) -> Response:
    """Remove up to fifty saved searches named by ``searchKey``."""
    library = await writes.lock_library(session, library)
    expected = writes.parse_version_header(request.headers.get("If-Unmodified-Since-Version"))
    writes.check_library_version(library, expected, required=True)

    keys = [k for k in (request.query_params.get("searchKey") or "").split(",") if k]
    if not keys:
        raise InvalidInputError("'searchKey' parameter not provided")
    if len(keys) > writes.MAX_OBJECTS:
        raise RequestTooLargeError(
            f"Cannot delete more than {writes.MAX_OBJECTS} searches at a time"
        )

    version = await writes.bump_library_version(session, library)
    await object_writes.delete_searches(session, library, keys, version, permit=access)
    await session.commit()

    return Response(status_code=204, headers=library_headers(version))
