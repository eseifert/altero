"""Record which file an upload registered for each attachment

A download served whatever file an attachment's ``md5`` field named, and that
field is metadata any client may write. ``items.registered_md5`` is the digest
an upload registered, which downloads serve instead.

Existing attachments are given the digest they claim, where they store a file
and it is one: until now that is what every download served, so nothing that
downloads today stops downloading.

Revision ID: c7d2a9e41b3f
Revises: a3f1c6d2e8b4
Create Date: 2026-10-28 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7d2a9e41b3f"
down_revision: str | Sequence[str] | None = "a3f1c6d2e8b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BACKFILL = """
UPDATE items SET registered_md5 = (
    SELECT lower(item_fields.value) FROM item_fields
    WHERE item_fields.item_id = items.id AND item_fields.field = 'md5'
)
WHERE items.item_type = 'attachment'
AND EXISTS (
    SELECT 1 FROM item_fields
    WHERE item_fields.item_id = items.id AND item_fields.field = 'linkMode'
    AND item_fields.value IN ('imported_file', 'imported_url', 'embedded_image')
)
"""

#: Whatever the backfill copied that is not a digest, per backend.
NOT_A_DIGEST = {
    "sqlite": "length(registered_md5) != 32 OR registered_md5 GLOB '*[^0-9a-f]*'",
    "postgresql": "registered_md5 !~ '^[0-9a-f]{32}$'",
}


def upgrade() -> None:
    with op.batch_alter_table("items") as batch:
        batch.add_column(sa.Column("registered_md5", sa.String(length=32), nullable=True))
    op.execute(BACKFILL)
    dialect = op.get_bind().dialect.name
    op.execute(f"UPDATE items SET registered_md5 = NULL WHERE {NOT_A_DIGEST[dialect]}")


def downgrade() -> None:
    with op.batch_alter_table("items") as batch:
        batch.drop_column("registered_md5")
