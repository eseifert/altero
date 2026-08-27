"""Name the territory a language is read in

The interface used to be keyed by language alone, so an account that asked for
Brazilian Portuguese was stored as `pt` and read Lisbon's words. Three languages
are now carried twice -- English, Portuguese and Chinese -- and a stored `en`,
`pt` or `zh` names no catalogue any more.

Each is sent where CLDR's likely subtags send a bare tag, which is the same
answer `services.locales.normalise_language` gives, so an account keeps the
words it had. Null is untouched: it means "follow the browser", and the browser
is now asked for its region too.

Revision ID: 2c7d1a94e5b0
Revises: 03fa7e161674
Create Date: 2026-08-27 21:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2c7d1a94e5b0"
down_revision: str | Sequence[str] | None = "03fa7e161674"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The bare tags that used to be stored, and the catalogue each now names.
VARIANTS = {"en": "en-US", "pt": "pt-BR", "zh": "zh-CN"}


def upgrade() -> None:
    """Upgrade schema."""
    users = sa.table("users", sa.column("language", sa.String))
    for bare, variant in VARIANTS.items():
        op.execute(
            users.update()
            .where(users.c.language == op.inline_literal(bare))
            .values(language=variant)
        )


def downgrade() -> None:
    """Downgrade schema."""
    users = sa.table("users", sa.column("language", sa.String))
    for bare, variant in VARIANTS.items():
        op.execute(
            users.update()
            .where(users.c.language.in_([variant, *_others(variant)]))
            .values(language=bare)
        )


def _others(variant: str) -> list[str]:
    """The other catalogues of the same language, which the old column cannot hold."""
    language = variant.partition("-")[0]
    return [tag for tag in ("en-GB", "pt-PT", "zh-TW") if tag.startswith(f"{language}-")]
