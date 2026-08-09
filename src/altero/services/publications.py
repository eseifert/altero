"""Putting an item into My Publications, and taking it out again.

``inPublications`` is one boolean on one item, and setting it is the whole of
what the v3 API knows about My Publications. The desktop client asks a good
deal more than that before it sets it, and this module is that conversation
made into a service call, so that the browser can offer the same thing the
desktop offers rather than a checkbox that publishes a book and quietly leaves
its files behind.

Two functions in ``Zotero.Items`` are the specification, and they are followed
line for line:

``addToPublications(items, options)`` (``chrome/content/zotero/xpcom/data/items.js``)
    Flags the items. With ``childNotes`` it flags their notes too; with
    ``childFileAttachments`` their stored attachments; ``childLinks`` covers
    link attachments, and a *linked file* is skipped whatever is asked for,
    because the server does not hold its bytes. With a ``license`` it writes
    the licence's name into the item's ``rights`` field, unless ``keepRights``
    is set and the item already says something there.

``removeFromPublications(items)``
    Refuses an item that is not in My Publications, and takes the item's notes
    and attachments out with it -- trashed ones included, since a trashed child
    is still published until something says otherwise.

Which of the wizard's answers reach here is the browser's business; what they
mean is decided in one place, and it is this one. Every write goes through
:func:`altero.services.itemwrites.save_item`, so an item published from the
browser is the item a syncing client would have written: same validation, same
timestamps, one library version for the lot.

The licence names are Zotero's own English ones, whatever language the account
reads in, and this is the one place altero does not follow the client: Zotero
writes the name in the language its window was showing, so the same licence
reaches the field as "Creative Commons Namensnennung 4.0 Internationale Lizenz"
from a German client and in English from a Japanese one. ``rights`` is data --
it is exported, cited and read by every other client -- rather than a label
this server draws, and altero has no message catalogue on the server side to
draw it with. One canonical name is the honest answer, and the interface shows
exactly the name that will be stored rather than a translation of it:
``web/src/publications/licenses.ts`` is the same table, and
``tests/test_web_publications.py`` fails if the two disagree.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import InvalidInputError
from altero.models import Item, Library, LibraryType
from altero.services import itemwrites

#: Attachments whose bytes this server holds, and which "include files" is
#: therefore about. ``linked_url`` is a bookmark and travels with the item
#: regardless (the client sets ``childLinks`` unconditionally on the drop);
#: ``linked_file`` points at somebody's disk and is never published.
STORED_LINK_MODES = frozenset({"imported_file", "imported_url"})


@dataclass(frozen=True, slots=True)
class License:
    """One answer to "how may this work be shared?"."""

    #: The client's identifier, which is what the browser sends.
    id: str
    #: What goes into the item's ``rights`` field.
    name: str
    #: Where the licence is published, for the interface to link to. ``None``
    #: for reserved rights, which are not a licence and have nowhere to point.
    url: str | None


#: The licences the wizard can arrive at, in the order it offers them.
#:
#: Taken from ``publicationsLicenseInfo.js`` and the ``licenses-*`` messages in
#: ``chrome/locale/en-US/zotero/zotero.ftl``. The client's generic ``cc`` is not
#: here: it is what its wizard reports while the licence is still being chosen,
#: and never an answer -- picking Creative Commons always leads to the page
#: that narrows it to one of the six below.
LICENSES: tuple[License, ...] = (
    License("reserved", "All rights reserved", None),
    License(
        "cc-by",
        "Creative Commons Attribution 4.0 International License",
        "https://creativecommons.org/licenses/by/4.0/",
    ),
    License(
        "cc-by-sa",
        "Creative Commons Attribution-ShareAlike 4.0 International License",
        "https://creativecommons.org/licenses/by-sa/4.0/",
    ),
    License(
        "cc-by-nd",
        "Creative Commons Attribution-NoDerivatives 4.0 International License",
        "https://creativecommons.org/licenses/by-nd/4.0/",
    ),
    License(
        "cc-by-nc",
        "Creative Commons Attribution-NonCommercial 4.0 International License",
        "https://creativecommons.org/licenses/by-nc/4.0/",
    ),
    License(
        "cc-by-nc-sa",
        "Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License",
        "https://creativecommons.org/licenses/by-nc-sa/4.0/",
    ),
    License(
        "cc-by-nc-nd",
        "Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International License",
        "https://creativecommons.org/licenses/by-nc-nd/4.0/",
    ),
    License(
        "cc0",
        "CC0 1.0 Universal Public Domain Dedication",
        "https://creativecommons.org/publicdomain/zero/1.0/",
    ),
)

_BY_ID = {entry.id: entry for entry in LICENSES}


def license_for(license_id: str) -> License:
    """Return the licence ``license_id`` names.

    Raises:
        InvalidInputError: if it names none of them. The alternative is writing
            whatever arrived into the ``rights`` field of a published item,
            which is a licence somebody may act on.
    """
    if (found := _BY_ID.get(license_id)) is None:
        raise InvalidInputError(f"'{license_id}' is not a licence this server offers")
    return found


async def children_of(session: AsyncSession, item: Item) -> list[Item]:
    """Every note and attachment hanging off ``item``, trashed ones included."""
    children = await session.scalars(
        select(Item).where(Item.parent_id == item.id).order_by(Item.id)
    )
    return list(children)


def _publishable(child: Item, *, include_files: bool, include_notes: bool) -> bool:
    """Whether a child goes along, given what was asked for."""
    if child.item_type == "note":
        return include_notes
    if child.item_type != "attachment":
        # An annotation lives on an attachment rather than on the item, and the
        # client's own drop passes `annotations: false`.
        return False

    link_mode = child.field_values().get("linkMode", "")
    if link_mode == "linked_file":
        return False
    if link_mode == "linked_url":
        return True
    return include_files and link_mode in STORED_LINK_MODES


async def add_to_publications(
    session: AsyncSession,
    library: Library,
    item: Item,
    version: int,
    *,
    include_files: bool = False,
    include_notes: bool = False,
    license_id: str | None = None,
    keep_rights: bool = True,
    actor_id: int | None = None,
) -> list[Item]:
    """Publish ``item``, with whichever of its children were asked for.

    Args:
        include_files: Whether stored attachments go along. Link attachments do
            regardless; linked files never do.
        include_notes: Whether child notes go along.
        license_id: The licence to record in the item's ``rights`` field, or
            ``None`` to leave the field alone -- which is what the wizard means
            when no files are being published and so nothing is being licensed.
        keep_rights: Whether a ``rights`` value the item already carries stands.

    Returns:
        Every item written, the parent first.

    Raises:
        InvalidInputError: if this is not a library that has a My Publications,
            or if the item cannot be in one. The refusals themselves are
            :mod:`altero.services.itemwrites`'s, so a book published from the
            browser is refused for exactly the reasons a syncing client's would
            be.
    """
    if library.type is not LibraryType.USER:
        # Said here as well as in the write, because the browser reaches this
        # with a library it chose and deserves the answer before the licence is
        # applied to anything.
        raise InvalidInputError("Group items cannot be added to My Publications")

    targets = [item]
    # A child item is published on its own -- that is the desktop's "Show in My
    # Publications" for a note or attachment its parent left behind -- and has
    # no children of its own to carry.
    if item.parent_id is None:
        targets += [
            child
            for child in await children_of(session, item)
            if _publishable(child, include_files=include_files, include_notes=include_notes)
        ]

    payload: dict[str, object] = {"inPublications": True}
    if license_id is not None:
        licence = license_for(license_id)
        # `!options.keepRights || !item.getField('rights')`: a licence the
        # reader chose replaces what is there only when they said it should.
        # Notes and attachments have no `rights` field at all, so the licence
        # is the parent's business and never a child's.
        if item.item_type not in ("note", "attachment") and (
            not keep_rights or not item.field_values().get("rights")
        ):
            payload["rights"] = licence.name

    written = []
    for target in targets:
        await itemwrites.save_item(
            session,
            library,
            payload if target is item else {"inPublications": True},
            version,
            key=target.key,
            replace=False,
            actor_id=actor_id,
        )
        written.append(target)
    return written


async def remove_from_publications(
    session: AsyncSession,
    library: Library,
    item: Item,
    version: int,
    *,
    actor_id: int | None = None,
) -> list[Item]:
    """Take ``item`` out of My Publications, and its children with it.

    Its children whatever they are and wherever they are: a published note that
    somebody trashed is still published, and leaving it behind would leave a
    fragment of the work on a page the reader believes they have emptied. The
    trashed stay trashed -- this write says one thing and says only that.

    Returns:
        Every item written, the parent first. A child that was not published is
        not one of them: it is already where this is trying to put it, and a
        new version on it would be a sync for nothing.

    Raises:
        InvalidInputError: if the item is not in My Publications. The client
            raises there too, and it is worth raising: an interface that offers
            to unpublish something that was never published is describing the
            library wrongly.
    """
    if not item.in_publications:
        raise InvalidInputError("Item is not in My Publications")

    targets = [item]
    if item.parent_id is None:
        targets += [child for child in await children_of(session, item) if child.in_publications]

    for target in targets:
        await itemwrites.save_item(
            session,
            library,
            {"inPublications": False},
            version,
            key=target.key,
            replace=False,
            actor_id=actor_id,
        )
    return targets
