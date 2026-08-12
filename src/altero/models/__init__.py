"""SQLAlchemy models.

Every model must be re-exported here so that Alembic's autogenerate sees the
complete metadata.
"""

from altero.models.activity import ActivityKind, GroupActivity, GroupActivityObject
from altero.models.apikey import ApiKey, ApiKeyGroupAccess
from altero.models.collection import (
    Collection,
    CollectionItem,
    CollectionRelation,
    CollectionShare,
)
from altero.models.fulltext import FullText
from altero.models.instance import InstanceSetting
from altero.models.item import Item, ItemCreator, ItemField, ItemRelation
from altero.models.library import (
    Group,
    GroupMember,
    Library,
    LibraryType,
    MemberPermission,
    ProfileVisibility,
    User,
)
from altero.models.login import LoginSession
from altero.models.search import SavedSearch, SearchCondition
from altero.models.setting import Setting
from altero.models.storage import StorageUpload
from altero.models.sync import DeletedObject, DeletedObjectType, WriteToken
from altero.models.tag import ItemTag, Tag, TagType
from altero.models.webauth import (
    EmailFactor,
    EmailVerification,
    Invitation,
    LoginCode,
    Notification,
    PasswordReset,
    TotpCredential,
    WebSession,
)

__all__ = [
    "ActivityKind",
    "ApiKey",
    "ApiKeyGroupAccess",
    "Collection",
    "CollectionItem",
    "CollectionRelation",
    "CollectionShare",
    "DeletedObject",
    "DeletedObjectType",
    "EmailFactor",
    "EmailVerification",
    "FullText",
    "Group",
    "GroupActivity",
    "GroupActivityObject",
    "GroupMember",
    "InstanceSetting",
    "Invitation",
    "Item",
    "ItemCreator",
    "ItemField",
    "ItemRelation",
    "ItemTag",
    "Library",
    "LibraryType",
    "LoginCode",
    "LoginSession",
    "MemberPermission",
    "Notification",
    "PasswordReset",
    "ProfileVisibility",
    "SavedSearch",
    "SearchCondition",
    "Setting",
    "StorageUpload",
    "Tag",
    "TagType",
    "TotpCredential",
    "User",
    "WebSession",
    "WriteToken",
]
