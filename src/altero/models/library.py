"""Libraries and their owners."""

from enum import StrEnum

from sqlalchemy import Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from altero.db import Base


class LibraryType(StrEnum):
    """The two library kinds addressable in the API's URL prefix."""

    USER = "user"
    GROUP = "group"


class User(Base):
    """A Zotero user account."""

    __tablename__ = "users"

    # The user ID appears in URLs, so it is assigned rather than generated.
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    username: Mapped[str] = mapped_column(String(255), unique=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")


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
