"""One person's public page, and who is allowed to read it.

A profile page is the answer to a promise the desktop client makes. Its
publishing wizard says, in every language it ships:

    Items you add to My Publications will be shown on your profile page on
    zotero.org. If you choose to include attached files, they will be made
    publicly available under the license you specify.

Upstream that page is ``zotero.org/<slug>``, built in ``Zotero_URI::getUserURI``
from the username put through ``Zotero_Utilities::slugify``, and it exists for
everyone whether or not anything is on it. altero serves the same page from its
own interface, at ``/app/u/<username>``, over the endpoints in
:mod:`altero.api.routes.webprofile`.

What is on it is exactly what ``/users/<id>/publications/items`` serves: the
items flagged ``inPublications``, their published children, and the files those
children hold. There is no second definition of "published" here, and no
second serialiser -- a profile page is a reading of the same list the sync
protocol reads.

Where altero adds something upstream has not got, it is the visibility setting
in :class:`~altero.models.ProfileVisibility`. zotero.org is a service and its
profiles are public full stop; this server is somebody's own, and "published"
on it can reasonably mean "to the people I share this instance with". The
default is upstream's behaviour, so nothing changes for an account that never
opens the setting.
"""

import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import NotFoundError
from altero.models import ApiKey, Item, Library, LibraryType, ProfileVisibility, User
from altero.query import ListQuery
from altero.services import auth, items

#: Characters upstream keeps in a profile slug, from ``Zotero_Utilities::slugify``:
#: lower case, then everything outside this set dropped, then spaces to
#: underscores. altero looks a username up rather than storing a slug, so this
#: is used to recognise the shape rather than to generate it.
_UNSLUGGABLE = re.compile(r"[^a-z0-9 ._-]")


def slugify(username: str) -> str:
    """Return the profile slug for ``username``, as upstream forms it.

    ``strtolower``, drop everything outside ``[a-z0-9 ._-]``, spaces to
    underscores -- ``Zotero_Utilities::slugify`` in the dataserver, kept here so
    a link altero writes to a profile matches the one zotero.org would.
    """
    return _UNSLUGGABLE.sub("", username.strip().lower()).replace(" ", "_")


async def find_by_username(session: AsyncSession, username: str) -> User:
    """Return the account ``username`` names, or raise :class:`NotFoundError`.

    Matched without regard to case, the way signing in matches it: a profile
    link is typed, said aloud and pasted between systems that fold case on
    their own, and ``/app/u/Ada`` reaching nobody while ``/app/u/ada`` reaches
    somebody would be a difference nobody can see in the address bar.

    The slug is tried second. A username may hold characters the slug drops --
    ``Ada Lovelace`` slugs to ``ada_lovelace`` -- so a link formed the way
    zotero.org forms one still arrives.
    """
    wanted = username.strip().lower()
    if not wanted:
        raise NotFoundError("No such profile")

    user = await session.scalar(select(User).where(func.lower(User.username) == wanted))
    if user is not None:
        return user

    # Nothing can slug to a string that is not itself a slug, so a name that
    # holds anything slugify would drop is already answered. That is what keeps
    # the pass below off the path a mistyped address takes.
    if slugify(wanted) != wanted:
        raise NotFoundError("No such profile")

    # One pass over the accounts rather than a stored slug column: two
    # usernames can share a slug (``Ada Lovelace`` and ``ada_lovelace``), and a
    # unique column would have to refuse the second registration for a reason
    # that has nothing to do with signing in.
    for candidate in await session.scalars(select(User).order_by(User.id)):
        if slugify(candidate.username) == wanted:
            return candidate

    raise NotFoundError("No such profile")


def visible_to(owner: User, viewer: User | None) -> bool:
    """Return whether ``viewer`` may read ``owner``'s profile.

    ``viewer`` is the signed-in account, or ``None`` for somebody who is not
    signed in -- which on a public profile is most of the world.

    The owner always may. The setting says who *else* can see the page, and an
    account that cannot see its own would have no way of checking what it had
    published before changing its mind.
    """
    if viewer is not None and viewer.id == owner.id:
        return True

    match owner.profile_visibility:
        case ProfileVisibility.PUBLIC:
            return True
        case ProfileVisibility.USERS:
            return viewer is not None
        case _:
            return False


async def readable_by_key(session: AsyncSession, library: Library, api_key: ApiKey | None) -> bool:
    """Return whether ``api_key`` may read ``library``'s publications.

    The v3 side of :func:`visible_to`, and the reason the setting is not
    decorative: ``/users/<id>/publications/items`` answers without a key, so a
    profile page that refused a stranger while the same items stayed one curl
    away would be a promise this server does not keep.

    The three settings say the same thing they say in the browser, read through
    the only credential the v3 API has:

    ``public``
        Anyone, with no key at all. Upstream's only behaviour, and the default.
    ``users``
        Any key this server issued -- the people with an account here.
    ``private``
        Only a key that could read the library anyway, which is the owner's
        own. Their desktop client goes on syncing My Publications either way.
    """
    owner = await session.get(User, library.owner_id)
    if owner is None:  # pragma: no cover - a personal library without its user
        return False

    match owner.profile_visibility:
        case ProfileVisibility.PUBLIC:
            return True
        case ProfileVisibility.USERS:
            return api_key is not None
        case _:
            return (await auth.get_access(session, library, api_key)).read


async def library_of(session: AsyncSession, user: User) -> Library:
    """Return ``user``'s personal library, which is where publications live."""
    library = await session.scalar(
        select(Library).where(Library.type == LibraryType.USER, Library.owner_id == user.id)
    )
    if library is None:  # pragma: no cover - a user without a library is not creatable
        raise NotFoundError("No such profile")
    return library


async def count_published(session: AsyncSession, library: Library) -> int:
    """Return how many works ``library`` publishes at the top level.

    Counted in the database rather than by listing them. ``list_items`` with an
    unlimited page would answer this too, and would do it by loading every
    published item into memory to take its length -- which is the whole
    bibliography fetched to draw one number under a heading.
    """
    query = ListQuery(limit=1)
    statement = await items.build_item_query(session, library, query, items.Scope.PUBLICATIONS_TOP)
    return await items.count_matches(session, statement, query, 0)


async def published_item(session: AsyncSession, library: Library, key: str) -> Item:
    """Return one published item, or report it absent.

    Absent rather than refused, for the reason the v3 endpoint gives: hiding an
    item from the listing is pointless if its key still fetches it. A published
    item in the trash is absent too -- upstream's ``$item->deleted`` check in
    ``ItemsController`` -- because the owner has taken it back.
    """
    item = await session.scalar(select(Item).where(Item.library_id == library.id, Item.key == key))
    if item is None or not item.in_publications or item.deleted:
        raise NotFoundError("Item does not exist")
    return item
