"""Store profile visibility as the enum's name

`40b83b1acb4c` added `users.profile_visibility` with `server_default='public'`,
which is the enum's *value*. SQLAlchemy's `Enum` persists the *name*, so every
row that existed when the column was added -- every account on every server
that had one -- was filled in with a string the mapper cannot read back:

    LookupError: 'public' is not among the defined enum values.
    Enum name: profilevisibility. Possible values: PUBLIC, USERS, PRIVATE

That is raised while loading a `User`, so it took out signing in, and nothing
in the suite saw it: the tests write the column through the model, which
writes the name, and only a row that never wrote it at all carries the default.
`tests/test_web_profiles.py::TestTheColumnsDefault` is that row, and fails
without this.

The earlier revision is left as it is -- databases are stamped with it -- so
the repair is here: rewrite the rows, then correct the default the column
carries for any row added later.

Revision ID: 4316d74eba15
Revises: 40b83b1acb4c
Create Date: 2026-08-09 18:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4316d74eba15"
down_revision: str | Sequence[str] | None = "40b83b1acb4c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The stored form of each setting, and the form the broken default wrote.
NAMES = {"public": "PUBLIC", "users": "USERS", "private": "PRIVATE"}

_VISIBILITY = sa.Enum(
    "PUBLIC", "USERS", "PRIVATE", name="profilevisibility", native_enum=False, length=8
)


def upgrade() -> None:
    """Upgrade schema."""
    # Only `public` can be there -- it was the default, and every other value
    # reached the column through the mapper -- but all three are named so that
    # a database written by some other route is repaired too.
    for value, name in NAMES.items():
        op.execute(
            sa.text(
                "UPDATE users SET profile_visibility = :name WHERE profile_visibility = :value"
            ).bindparams(name=name, value=value)
        )

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column(
            "profile_visibility", existing_type=_VISIBILITY, server_default="PUBLIC"
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column(
            "profile_visibility", existing_type=_VISIBILITY, server_default="public"
        )
