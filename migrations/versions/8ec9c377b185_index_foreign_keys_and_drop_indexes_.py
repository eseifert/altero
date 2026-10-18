"""Index foreign keys and drop indexes nothing uses alone

Foreign keys with no index of their own are indexed: PostgreSQL creates none
for a referencing column, and SQLite scans the referencing table to apply
``ON DELETE``, so deleting an account read every item in the instance to null
``last_modified_by_user_id``. That one is partial, since only a group library's
items carry it. ``group_members.user_id`` is the hot one: the key leads with the
library, and "which groups is this person in" is asked on every library list.

Dropped are indexes that are a leading prefix of another index or unique
constraint on the same table, and the single ``version`` and
``server_date_modified`` indexes of collections, tags, searches, settings, the
delete log and full text, every filter on which comes with the library.

The three item sort indexes spanned every library. They are replaced by the
same sorts behind ``library_id``, which measured the same on both backends and
cannot lead a planner through the whole instance to sort one small library.

Revision ID: 8ec9c377b185
Revises: 5c3e8f1a9d27
Create Date: 2026-10-18 19:24:12.377970

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8ec9c377b185"
down_revision: str | Sequence[str] | None = "5c3e8f1a9d27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Foreign keys that gain an index: name, table, column.
ADDED = [
    ("ix_api_key_group_access_library_id", "api_key_group_access", "library_id"),
    ("ix_auth_requests_user_id", "auth_requests", "user_id"),
    ("ix_collection_shares_created_by_user_id", "collection_shares", "created_by_user_id"),
    ("ix_group_activity_actor_id", "group_activity", "actor_id"),
    ("ix_group_members_user_id", "group_members", "user_id"),
    ("ix_groups_owner_id", "groups", "owner_id"),
    ("ix_invitations_invited_by", "invitations", "invited_by"),
    ("ix_login_sessions_api_key_id", "login_sessions", "api_key_id"),
    ("ix_notifications_invitation_id", "notifications", "invitation_id"),
    ("ix_password_resets_issued_by", "password_resets", "issued_by"),
    ("ix_storage_downloads_library_id", "storage_downloads", "library_id"),
    ("ix_storage_uploads_library_id", "storage_uploads", "library_id"),
    ("ix_webauthn_challenges_user_id", "webauthn_challenges", "user_id"),
]

#: Item sorts, from the index across every library to the one behind it.
SORTS = {
    "ix_items_sort_title": ("ix_items_library_sort_title", "sort_title"),
    "ix_items_sort_creator": ("ix_items_library_sort_creator", "sort_creator"),
    "ix_items_sort_date": ("ix_items_library_sort_date", "sort_date"),
}

#: Indexes dropped: name, table, column.
DROPPED = [
    ("ix_collections_library_id", "collections", "library_id"),
    ("ix_collections_server_date_modified", "collections", "server_date_modified"),
    ("ix_collections_version", "collections", "version"),
    ("ix_deleted_objects_library_id", "deleted_objects", "library_id"),
    ("ix_deleted_objects_version", "deleted_objects", "version"),
    ("ix_federated_identities_provider_id", "federated_identities", "provider_id"),
    ("ix_item_fulltext_library_id", "item_fulltext", "library_id"),
    ("ix_item_fulltext_version", "item_fulltext", "version"),
    ("ix_oauth_grant_resources_grant_id", "oauth_grant_resources", "grant_id"),
    ("ix_oauth_grants_user_id", "oauth_grants", "user_id"),
    ("ix_searches_library_id", "searches", "library_id"),
    ("ix_searches_server_date_modified", "searches", "server_date_modified"),
    ("ix_searches_version", "searches", "version"),
    ("ix_settings_library_id", "settings", "library_id"),
    ("ix_settings_version", "settings", "version"),
    ("ix_tags_library_id", "tags", "library_id"),
    ("ix_tags_server_date_modified", "tags", "server_date_modified"),
    ("ix_tags_version", "tags", "version"),
    ("ix_write_tokens_library_id", "write_tokens", "library_id"),
]

#: Only a group library's items record who last changed them.
CHANGED_BY = sa.text("last_modified_by_user_id IS NOT NULL")


def upgrade() -> None:
    """Upgrade schema."""
    for name, table, column in ADDED:
        op.create_index(name, table, [column], unique=False)
    op.create_index(
        "ix_items_last_modified_by_user_id",
        "items",
        ["last_modified_by_user_id"],
        unique=False,
        postgresql_where=CHANGED_BY,
        sqlite_where=CHANGED_BY,
    )
    for old, (new, column) in SORTS.items():
        op.create_index(new, "items", ["library_id", column], unique=False)
        op.drop_index(old, table_name="items")
    for name, table, _column in DROPPED:
        op.drop_index(name, table_name=table)


def downgrade() -> None:
    """Downgrade schema."""
    for name, table, column in DROPPED:
        op.create_index(name, table, [column], unique=False)
    for old, (new, column) in SORTS.items():
        op.create_index(old, "items", [column], unique=False)
        op.drop_index(new, table_name="items")
    op.drop_index("ix_items_last_modified_by_user_id", table_name="items")
    for name, table, _column in ADDED:
        op.drop_index(name, table_name=table)
