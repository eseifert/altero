"""Let a revoked key take its login session's reference with it

``login_sessions.api_key_id`` pointed at the key the handshake handed out with
no ``ON DELETE``, so revoking that key was a foreign key violation: a 500 from
``DELETE /keys/current``, which is what unlinking the client does, and from
every other way a key is revoked. Every key a desktop client holds comes from
that handshake, so every one of them was un-revokable.

The reference is cleared rather than the row deleted, matching what
``services.admin.delete_user`` already did by hand and what
``services.login.render`` already expected: a completed session whose key has
gone reports itself cancelled. The constraint is named on the way past, the
anonymous one the initial schema created being undroppable on PostgreSQL.

Revision ID: a1d7c4e90b32
Revises: 63853f22a780
Create Date: 2026-09-12 21:40:12.118904

"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "a1d7c4e90b32"
down_revision: str | Sequence[str] | None = "63853f22a780"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME = "fk_login_sessions_api_key_id"
# Names the constraint the initial schema left anonymous, so that batch mode has
# something to drop. SQLite reports no name for it at all; PostgreSQL generated
# `login_sessions_api_key_id_fkey` and reflection below finds whichever it is.
CONVENTION = {"fk": "fk_%(table_name)s_%(column_0_name)s"}


def _existing_name() -> str:
    """Return the current constraint's name, or the one batch mode will invent."""
    for fk in inspect(op.get_bind()).get_foreign_keys("login_sessions"):
        if fk["constrained_columns"] == ["api_key_id"]:
            return fk["name"] or NAME
    return NAME


def upgrade() -> None:
    """Upgrade schema."""
    existing = _existing_name()
    with op.batch_alter_table(
        "login_sessions", schema=None, naming_convention=CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(existing, type_="foreignkey")
        batch_op.create_foreign_key(NAME, "api_keys", ["api_key_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table(
        "login_sessions", schema=None, naming_convention=CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(NAME, type_="foreignkey")
        batch_op.create_foreign_key(NAME, "api_keys", ["api_key_id"], ["id"])
