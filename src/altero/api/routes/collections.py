"""Collection endpoints."""

from collections.abc import Sequence
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
    ApiKeyDep,
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
from altero.api.routes.items import FEED_DESCRIPTIONS, render_page
from altero.errors import InvalidInputError, RequestTooLargeError
from altero.models import ActivityKind, Collection, Library
from altero.query import (
    NAMED_SORT_FIELDS,
    OBJECT_FORMATS,
    SINGLE_NAMED_FORMATS,
    Format,
    ListQuery,
    parse_list_query,
)
from altero.services import auth, writes
from altero.services import collections as collections_service
from altero.services import items as items_service
from altero.services import objectwrites as object_writes
from altero.services.collections import Page
from altero.services.items import Scope

router = APIRouter(tags=["collections"])


def collection_query(request: Request, formats: frozenset[Format] = OBJECT_FORMATS) -> ListQuery:
    return parse_list_query(
        list(request.query_params.multi_items()),
        sort_fields=NAMED_SORT_FIELDS,
        default_sort="title",
        formats=formats,
    )


async def render_collections(
    session: AsyncSession, collections: Sequence[Collection], library: Library, base_url: str
) -> list[dict[str, Any]]:
    """Serialize collections, gathering the counts their envelopes report.

    Fetched once for the whole page rather than once per collection, for the
    reason given in :func:`altero.api.routes.items.render_items`.
    """
    subcollections = await collections_service.count_subcollections(session, collections)
    items = await collections_service.count_items(session, collections)
    parent_keys = await collections_service.parent_keys_for(session, collections)

    return [
        serializers.collection(
            collection,
            library,
            base_url,
            num_collections=subcollections.get(collection.id, 0),
            num_items=items.get(collection.id, 0),
            parent_key=parent_keys.get(collection.parent_id) if collection.parent_id else None,
        )
        for collection in collections
    ]


async def render_collection(
    session: AsyncSession, collection: Collection, library: Library, base_url: str
) -> dict[str, Any]:
    """Serialize one collection."""
    (rendered,) = await render_collections(session, [collection], library, base_url)
    return rendered


async def _render_page(
    request: Request,
    session: AsyncSession,
    page: Page[Collection],
    library: Library,
    base_url: str,
    query: ListQuery,
    describes: str = "Collections",
) -> Response:
    objects: list[Any] = []
    feed: AtomFeed | None = None

    if query.response_format is Format.JSON:
        objects = await render_collections(session, page.objects, library, base_url)
    elif query.response_format is Format.ATOM:
        envelopes = await render_collections(session, page.objects, library, base_url)
        feed = AtomFeed(
            describes=describes,
            author=atom.author_for(library, base_url),
            entries=tuple(
                atom.collection_entry(envelope, query.content, timestamps=_timestamps(collection))
                for envelope, collection in zip(envelopes, page.objects, strict=True)
            ),
            empty_updated=serializers.timestamp(datetime.now(UTC).replace(tzinfo=None)),
        )

    return listing_response(
        request,
        query,
        version=page.library_version,
        total=page.total,
        objects=objects,
        keys=[collection.key for collection in page.objects],
        versions={collection.key: collection.version for collection in page.objects},
        feed=feed,
    )


def _timestamps(obj: Collection) -> tuple[str, str]:
    """Return an object's ``published`` and ``updated``.

    A collection's JSON envelope carries neither -- the API publishes only an
    item's -- so an Atom entry reads them off the stored row.
    """
    return serializers.timestamp(obj.date_added), serializers.timestamp(obj.date_modified)


@router.get("/users/{user_id}/collections")
@router.get("/groups/{group_id}/collections")
async def list_collections(
    request: Request, session: SessionDep, library: ReadableLibraryDep, base_url: BaseUrlDep
) -> Response:
    query = collection_query(request)
    if (response := not_modified(request, library.version)) is not None:
        return response

    page = await collections_service.list_collections(session, library, query)
    return await _render_page(request, session, page, library, base_url, query)


@router.get("/users/{user_id}/collections/top")
@router.get("/groups/{group_id}/collections/top")
async def list_top_collections(
    request: Request, session: SessionDep, library: ReadableLibraryDep, base_url: BaseUrlDep
) -> Response:
    query = collection_query(request)
    page = await collections_service.list_collections(session, library, query, top_only=True)
    return await _render_page(request, session, page, library, base_url, query)


@router.get("/users/{user_id}/collections/{collection_key}")
@router.get("/groups/{group_id}/collections/{collection_key}")
async def get_collection(
    collection_key: str,
    request: Request,
    session: SessionDep,
    library: ReadableLibraryDep,
    base_url: BaseUrlDep,
) -> Response:
    query = collection_query(request, SINGLE_NAMED_FORMATS)
    if (response := not_modified(request, library.version)) is not None:
        return response

    collection = await collections_service.get_collection(session, library, collection_key)
    envelope = await render_collection(session, collection, library, base_url)

    if query.response_format is Format.ATOM:
        return entry_response(
            atom.collection_entry(envelope, query.content, timestamps=_timestamps(collection)),
            atom.author_for(library, base_url),
            library.version,
        )

    return object_response(envelope, library.version)


@router.get("/users/{user_id}/collections/{collection_key}/collections")
@router.get("/groups/{group_id}/collections/{collection_key}/collections")
async def list_subcollections(
    collection_key: str,
    request: Request,
    session: SessionDep,
    library: ReadableLibraryDep,
    base_url: BaseUrlDep,
) -> Response:
    query = collection_query(request)
    page = await collections_service.list_collections(
        session, library, query, parent_key=collection_key
    )
    describes = ""
    if query.response_format is Format.ATOM:
        parent = await collections_service.get_collection(session, library, collection_key)
        describes = f"Child Collections of ‘{parent.name}’"  # noqa: RUF001
    return await _render_page(request, session, page, library, base_url, query, describes)


async def _collection_feed_title(
    session: AsyncSession,
    library: Library,
    query: ListQuery,
    scope: Scope,
    collection_key: str,
) -> str:
    """Return what a feed of a collection's items says it covers.

    Empty for every other format, so a JSON listing does not pay for the extra
    lookup the title needs.
    """
    if query.response_format is not Format.ATOM:
        return ""
    collection = await collections_service.get_collection(session, library, collection_key)
    return FEED_DESCRIPTIONS[scope].format(name=collection.name)


@router.get("/users/{user_id}/collections/{collection_key}/items")
@router.get("/groups/{group_id}/collections/{collection_key}/items")
async def list_collection_items(
    collection_key: str,
    request: Request,
    session: SessionDep,
    library: ReadableLibraryDep,
    access: AccessDep,
    base_url: BaseUrlDep,
) -> Response:
    from altero.api.routes.items import item_query

    query = item_query(request)
    page = await items_service.list_items(
        session, library, query, Scope.COLLECTION, collection_key, include_notes=access.notes
    )
    return await render_page(
        request,
        session,
        page,
        library,
        base_url,
        query,
        await _collection_feed_title(session, library, query, Scope.COLLECTION, collection_key),
        include_notes=access.notes,
    )


@router.get("/users/{user_id}/collections/{collection_key}/items/top")
@router.get("/groups/{group_id}/collections/{collection_key}/items/top")
async def list_top_collection_items(
    collection_key: str,
    request: Request,
    session: SessionDep,
    library: ReadableLibraryDep,
    access: AccessDep,
    base_url: BaseUrlDep,
) -> Response:
    from altero.api.routes.items import item_query

    query = item_query(request)
    page = await items_service.list_items(
        session, library, query, Scope.COLLECTION_TOP, collection_key, include_notes=access.notes
    )
    return await render_page(
        request,
        session,
        page,
        library,
        base_url,
        query,
        await _collection_feed_title(session, library, query, Scope.COLLECTION_TOP, collection_key),
        include_notes=access.notes,
    )


@router.post("/users/{user_id}/collections")
@router.post("/groups/{group_id}/collections")
async def create_collections(
    request: Request,
    session: SessionDep,
    library: WritableLibraryDep,
    access: AccessDep,
    base_url: BaseUrlDep,
    api_key: ApiKeyDep,
) -> Response:
    """Create or update a batch of collections.

    Each object is a *diff* against what is stored, which is what
    ``updateMultipleFromJSON`` means by passing ``$partialUpdate = true`` for
    the whole batch. The desktop client relies on it: with the previous version
    in its ``syncCache`` it uploads only what changed, so a collection sent to
    the trash arrives as ``{key, version, deleted}`` and nothing else. A new
    collection is still a new collection and must carry a name --
    ``save_collection`` reads an object as partial only when it names one that
    exists, which is upstream's ``$partialUpdate && $exists``.
    """

    async def save(
        session: AsyncSession, library: Library, payload: dict[str, Any], version: int
    ) -> dict[str, Any] | None:
        collection = await object_writes.save_collection(
            session,
            library,
            payload,
            version,
            detect_unchanged=True,
            replace=False,
            permit=access,
        )
        if collection is None:
            return None
        return await render_collection(session, collection, library, base_url)

    return await batch_write(
        request,
        session,
        library,
        save,
        kind=ActivityKind.COLLECTIONS_CHANGED,
        actor_id=api_key.user_id if api_key else None,
    )


@router.put("/users/{user_id}/collections/{collection_key}")
@router.put("/groups/{group_id}/collections/{collection_key}")
async def replace_collection(
    collection_key: str,
    request: Request,
    session: SessionDep,
    library: WritableLibraryDep,
    access: AccessDep,
) -> Response:
    """Replace one collection. Properties left out are cleared."""
    return await _write_single(collection_key, request, session, library, access, replace=True)


@router.patch("/users/{user_id}/collections/{collection_key}")
@router.patch("/groups/{group_id}/collections/{collection_key}")
async def update_collection(
    collection_key: str,
    request: Request,
    session: SessionDep,
    library: WritableLibraryDep,
    access: AccessDep,
) -> Response:
    """Update one collection in place. Properties left out are untouched."""
    return await _write_single(collection_key, request, session, library, access, replace=False)


async def _write_single(
    collection_key: str,
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

    await collections_service.get_collection(session, library, collection_key)
    version = await writes.bump_library_version(session, library)
    await object_writes.save_collection(
        session,
        library,
        payload,
        version,
        key=collection_key,
        replace=replace,
        require_version=True,
        permit=access,
    )
    await session.commit()

    return Response(status_code=204, headers=library_headers(version))


@router.delete("/users/{user_id}/collections/{collection_key}")
@router.delete("/groups/{group_id}/collections/{collection_key}")
async def delete_collection(
    collection_key: str,
    request: Request,
    session: SessionDep,
    library: WritableLibraryDep,
    access: AccessDep,
) -> Response:
    """Remove one collection. Nested collections move up to its parent."""
    library = await writes.lock_library(session, library)
    expected = writes.parse_version_header(request.headers.get("If-Unmodified-Since-Version"))
    writes.check_library_version(library, expected, required=True)

    await collections_service.get_collection(session, library, collection_key)
    version = await writes.bump_library_version(session, library)
    await object_writes.delete_collections(
        session, library, [collection_key], version, permit=access
    )
    await session.commit()

    return Response(status_code=204, headers=library_headers(version))


@router.delete("/users/{user_id}/collections")
@router.delete("/groups/{group_id}/collections")
async def delete_collections(
    request: Request,
    session: SessionDep,
    library: WritableLibraryDep,
    access: AccessDep,
) -> Response:
    """Remove up to fifty collections named by ``collectionKey``."""
    library = await writes.lock_library(session, library)
    expected = writes.parse_version_header(request.headers.get("If-Unmodified-Since-Version"))
    writes.check_library_version(library, expected, required=True)

    keys = [k for k in (request.query_params.get("collectionKey") or "").split(",") if k]
    if not keys:
        raise InvalidInputError("'collectionKey' parameter not provided")
    if len(keys) > writes.MAX_OBJECTS:
        raise RequestTooLargeError(
            f"Cannot delete more than {writes.MAX_OBJECTS} collections at a time"
        )

    version = await writes.bump_library_version(session, library)
    await object_writes.delete_collections(session, library, keys, version, permit=access)
    await session.commit()

    return Response(status_code=204, headers=library_headers(version))
