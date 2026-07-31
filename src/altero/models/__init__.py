"""SQLAlchemy models.

Every model must be re-exported here so that Alembic's autogenerate sees the
complete metadata.
"""

from altero.models.apikey import ApiKey, ApiKeyGroupAccess
from altero.models.collection import Collection, CollectionItem
from altero.models.fulltext import FullText
from altero.models.item import Item, ItemCreator, ItemField, ItemRelation
from altero.models.library import Group, GroupMember, Library, LibraryType, User
from altero.models.login import LoginSession
from altero.models.search import SavedSearch, SearchCondition
from altero.models.setting import Setting
from altero.models.storage import StorageUpload
from altero.models.sync import DeletedObject, DeletedObjectType, WriteToken
from altero.models.tag import ItemTag, Tag, TagType

__all__ = [
    "ApiKey",
    "ApiKeyGroupAccess",
    "Collection",
    "CollectionItem",
    "DeletedObject",
    "DeletedObjectType",
    "FullText",
    "Group",
    "GroupMember",
    "Item",
    "ItemCreator",
    "ItemField",
    "ItemRelation",
    "ItemTag",
    "Library",
    "LibraryType",
    "LoginSession",
    "SavedSearch",
    "SearchCondition",
    "Setting",
    "StorageUpload",
    "Tag",
    "TagType",
    "User",
    "WriteToken",
]
