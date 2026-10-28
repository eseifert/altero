"""Name stored files by their own content

A snapshot ZIP was stored under the digest of the file inside it, which any
upload or archive could claim, so the bytes behind a digest could be replaced
by whoever claimed it. Files are now named by the digest of their own bytes,
and ``items.registered_zip`` records which registered files are ZIPs around
the attachment's file -- a fact the name used to carry.

The files themselves are renamed when the server next starts, against the
store it is configured with (`altero.services.storelayout`): a migration does
not know where the store is. Downgrading below this revision after that needs
the store as it was too, since an earlier altero looks for a snapshot under the
digest of the file inside it.

Revision ID: e5b8c1f07a26
Revises: c7d2a9e41b3f
Create Date: 2026-10-28 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5b8c1f07a26"
down_revision: str | Sequence[str] | None = "c7d2a9e41b3f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("items") as batch:
        batch.add_column(
            sa.Column("registered_zip", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("items") as batch:
        batch.drop_column("registered_zip")
