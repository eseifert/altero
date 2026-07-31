"""Helpers that put objects into the database for a test to work against."""

from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import (
    ApiKey,
    Collection,
    CollectionItem,
    Group,
    GroupMember,
    Item,
    ItemCreator,
    ItemField,
    ItemTag,
    Library,
    LibraryType,
    SavedSearch,
    SearchCondition,
    Tag,
    User,
)


async def make_user(
    session: AsyncSession,
    user_id: int = 1,
    username: str = "octocat",
    display_name: str = "Mona Lisa",
) -> User:
    """Create a user together with their personal library."""
    user = User(id=user_id, username=username, display_name=display_name)
    session.add(user)
    session.add(Library(type=LibraryType.USER, owner_id=user_id, name=display_name or username))
    await session.commit()
    return user


async def make_library(
    session: AsyncSession,
    *,
    library_type: LibraryType = LibraryType.USER,
    owner_id: int = 1,
    name: str = "",
    public: bool = False,
) -> Library:
    library = Library(type=library_type, owner_id=owner_id, name=name, public=public)
    session.add(library)
    await session.commit()
    return library


async def make_group(
    session: AsyncSession,
    *,
    group_id: int = 100,
    owner_id: int = 1,
    name: str = "Test Group",
    public: bool = False,
    members: dict[int, str] | None = None,
) -> Library:
    """Create a group library with its metadata and membership rows."""
    library = Library(type=LibraryType.GROUP, owner_id=group_id, name=name, public=public)
    session.add(library)
    await session.flush()

    session.add(Group(library_id=library.id, owner_id=owner_id, name=name))
    session.add(GroupMember(library_id=library.id, user_id=owner_id, role="admin"))
    for user_id, role in (members or {}).items():
        session.add(GroupMember(library_id=library.id, user_id=user_id, role=role))

    await session.commit()
    return library


async def make_api_key(
    session: AsyncSession,
    *,
    key: str = "P9NiFoyLeZu2bZNvvuQPDWsd",
    user_id: int = 1,
    name: str = "Test key",
    library_read: bool = True,
    library_write: bool = True,
    notes_read: bool = True,
    files_read: bool = True,
    all_groups_read: bool = False,
    all_groups_write: bool = False,
) -> ApiKey:
    api_key = ApiKey(
        key=key,
        user_id=user_id,
        name=name,
        library_read=library_read,
        library_write=library_write,
        notes_read=notes_read,
        files_read=files_read,
        all_groups_read=all_groups_read,
        all_groups_write=all_groups_write,
    )
    session.add(api_key)
    await session.commit()
    return api_key


async def make_item(
    session: AsyncSession,
    library: Library,
    *,
    key: str | None = None,
    item_type: str = "book",
    version: int = 1,
    fields: dict[str, str] | None = None,
    creators: list[tuple[str, str, str]] | None = None,
    parent: Item | None = None,
    deleted: bool = False,
) -> Item:
    """Create an item with its fields, creators and derived sort keys.

    Args:
        creators: ``(creatorType, firstName, lastName)`` triples.
    """
    from altero.keys import generate_key
    from altero.services.itemdata import derive_sort_creator, derive_sort_date, derive_sort_title

    fields = fields or {}
    item = Item(
        library_id=library.id,
        key=key or generate_key(),
        version=version,
        item_type=item_type,
        parent_id=parent.id if parent else None,
        deleted=deleted,
    )
    item.fields = [ItemField(field=name, value=value) for name, value in fields.items()]
    item.creators = [
        ItemCreator(position=index, creator_type=type_, first_name=first, last_name=last)
        for index, (type_, first, last) in enumerate(creators or [])
    ]
    item.sort_title = derive_sort_title(item_type, fields)
    item.sort_creator = derive_sort_creator(item.creators)
    item.sort_date = derive_sort_date(item_type, fields)

    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


async def make_collection(
    session: AsyncSession,
    library: Library,
    *,
    key: str | None = None,
    name: str = "Collection",
    version: int = 1,
    parent: Collection | None = None,
    items: list[Item] | None = None,
) -> Collection:
    from altero.keys import generate_key

    collection = Collection(
        library_id=library.id,
        key=key or generate_key(),
        name=name,
        version=version,
        parent_id=parent.id if parent else None,
    )
    session.add(collection)
    await session.flush()

    for item in items or []:
        session.add(CollectionItem(collection_id=collection.id, item_id=item.id))

    await session.commit()
    await session.refresh(collection)
    return collection


async def make_search(
    session: AsyncSession,
    library: Library,
    *,
    key: str | None = None,
    name: str = "Search",
    version: int = 1,
    conditions: list[tuple[str, str, str]] | None = None,
) -> SavedSearch:
    from altero.keys import generate_key

    search = SavedSearch(
        library_id=library.id, key=key or generate_key(), name=name, version=version
    )
    search.conditions = [
        SearchCondition(position=index, condition=condition, operator=operator, value=value)
        for index, (condition, operator, value) in enumerate(conditions or [])
    ]
    session.add(search)
    await session.commit()
    await session.refresh(search)
    return search


async def tag_item(
    session: AsyncSession,
    library: Library,
    item: Item,
    name: str,
    *,
    tag_type: int = 0,
    version: int = 1,
) -> Tag:
    """Attach a tag to an item, creating the tag if needed."""
    from sqlalchemy import select

    tag = await session.scalar(select(Tag).where(Tag.library_id == library.id, Tag.name == name))
    if tag is None:
        tag = Tag(library_id=library.id, name=name, version=version)
        session.add(tag)
        await session.flush()

    session.add(ItemTag(item_id=item.id, tag_id=tag.id, type=tag_type))
    await session.commit()
    return tag
