"""Libraries and their owners."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from altero.db import Base


class LibraryType(StrEnum):
    """The two library kinds addressable in the API's URL prefix."""

    USER = "user"
    GROUP = "group"


class ProfileVisibility(StrEnum):
    """Who may read an account's profile page, and its published items with it.

    Upstream has no such setting: zotero.org shows everyone's profile to
    everyone, and the dataserver serves ``/users/<id>/publications/items``
    without a key to whoever asks. :data:`PUBLIC` is that behaviour and is the
    default, so an existing account's publications stay exactly as reachable as
    they were. The other two exist because this server is somebody's own rather
    than a service, and "published" there can reasonably mean "to the people I
    share this instance with" or "to my own clients only".
    """

    #: Anyone, with no account and no key. What publishing means upstream, and
    #: what the desktop client's wizard promises.
    PUBLIC = "public"
    #: Anybody holding an account on this instance.
    USERS = "users"
    #: Nobody but the owner. The items stay in My Publications and stay
    #: flagged, so turning the profile back on republishes them unchanged.
    PRIVATE = "private"


class User(Base):
    """A Zotero user account."""

    __tablename__ = "users"

    # The user ID appears in URLs, so it is assigned rather than generated.
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    username: Mapped[str] = mapped_column(String(255), unique=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    #: Argon2id, or ``None`` for an account provisioned by `altero user add`
    #: that has never set one. Such an account works with an API key and cannot
    #: sign in to the web interface -- see :mod:`altero.services.webauth`.
    password_hash: Mapped[str | None] = mapped_column(String(255), default=None)
    password_changed: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    #: Stored folded to lower case, so one address cannot be held twice in
    #: different case. Null for an account made by `altero user add`, which
    #: needs no address to sync.
    email: Mapped[str | None] = mapped_column(String(320), unique=True, default=None)
    #: When the address was confirmed, or null. Gates security mail and
    #: nothing else -- an unverified account signs in and syncs normally.
    email_verified: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    #: Interface language as a BCP 47 tag, or null to follow the browser. Null
    #: is the setting rather than the absence of one: storing the language the
    #: browser happened to ask for would freeze it against a person who travels
    #: between machines with different ones.
    language: Mapped[str | None] = mapped_column(String(35), default=None)
    #: IANA time zone, or null to follow the browser for the same reason. Not a
    #: UTC offset: an offset is wrong for half the year everywhere that keeps
    #: summer time.
    time_zone: Mapped[str | None] = mapped_column(String(64), default=None)
    #: Whether this account administers the instance rather than a library.
    #: The one permission in altero that is not per library: it says who may
    #: see what the instance costs, set retention and take an account out of
    #: service. It grants nothing over anybody's library -- see
    #: :mod:`altero.api.routes.webadmin`.
    administrator: Mapped[bool] = mapped_column(default=False, server_default=false())
    #: When this account was taken out of service, or null. Refuses both
    #: credentials -- an API key and a browser session alike -- and touches
    #: nothing it owns: access stops, the data stays, and reinstating it is
    #: clearing this column.
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    #: Who may read this account's profile page and the items it publishes.
    #: Public by default, which is upstream's only behaviour and the one the
    #: publishing wizard describes.
    #: The default is the enum's *name*, not its value. ``Enum`` persists the
    #: name -- the column holds ``PUBLIC``, not ``public`` -- so a value here
    #: would be written into every row the column was added to and then fail to
    #: read back: "'public' is not among the defined enum values".
    profile_visibility: Mapped[ProfileVisibility] = mapped_column(
        Enum(ProfileVisibility, native_enum=False, length=8),
        default=ProfileVisibility.PUBLIC,
        server_default=ProfileVisibility.PUBLIC.name,
    )


class Library(Base):
    """A personal or group library, and the owner of the version counter."""

    __tablename__ = "libraries"
    __table_args__ = (UniqueConstraint("type", "owner_id", name="uq_libraries_type_owner"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[LibraryType] = mapped_column(Enum(LibraryType, native_enum=False, length=8))
    #: The user ID or group ID that identifies this library in the URL prefix.
    owner_id: Mapped[int] = mapped_column(index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    #: Incremented once per write; stamped onto every object that write touches.
    version: Mapped[int] = mapped_column(default=0)
    #: Public libraries are readable without a credential.
    public: Mapped[bool] = mapped_column(default=False)


class Group(Base):
    """Metadata specific to a group library."""

    __tablename__ = "groups"

    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id"), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(255), default="")
    type: Mapped[str] = mapped_column(String(32), default="Private")
    description: Mapped[str] = mapped_column(String, default="")
    url: Mapped[str] = mapped_column(String(255), default="")
    library_editing: Mapped[str] = mapped_column(String(16), default="members")
    library_reading: Mapped[str] = mapped_column(String(16), default="members")
    file_editing: Mapped[str] = mapped_column(String(16), default="members")


class GroupMember(Base):
    """Membership of a user in a group library."""

    __tablename__ = "group_members"

    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), default="member")

    #: What this member has asked to be told about, one flag per
    #: :class:`~altero.models.activity.ActivityKind`. Held here rather than on
    #: the account because "tell me about this library" is what people want:
    #: somebody in five groups usually cares about one, and an account-wide
    #: switch would make them choose between silence and all five.
    #:
    #: All off. altero sends nothing that is not a direct consequence of a
    #: request, and an upgrade that began mailing every member of every group
    #: would be exactly that.
    notify_items_changed: Mapped[bool] = mapped_column(default=False)
    notify_items_deleted: Mapped[bool] = mapped_column(default=False)
    notify_members_changed: Mapped[bool] = mapped_column(default=False)
    notify_collections_changed: Mapped[bool] = mapped_column(default=False)
