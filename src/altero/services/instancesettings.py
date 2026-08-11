"""Policies that belong to the operator rather than to a library.

Two sources, and the order between them is the point. A stored row wins; where
there is none, the ``ALTERO_``-prefixed configuration supplies the value. So an
operator who keeps everything in ``config.py`` keeps working and sees their own
numbers on the screen, a fresh instance needs no rows at all, and clearing a
setting returns it to whatever the deployment configured rather than to a
number this module invented.

Not a free-form store. Each setting is declared here with its bounds, because
these are periods after which data is deleted: a typo that stored ``0.5`` or
``-1`` or ``"thirty"`` would either turn a sweep off silently or delete
something nobody meant to lose.
"""

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import InvalidInputError, NotFoundError
from altero.models import InstanceSetting
from altero.settings import Settings


@dataclass(frozen=True, slots=True)
class Definition:
    """One setting: what it is called, where its default comes from, its range."""

    #: The name in the API and in the database, in camel case as the rest of
    #: ``/web`` is.
    name: str
    #: The :class:`~altero.settings.Settings` field supplying the default.
    field: str
    #: Largest value that means anything. A period longer than this is a way
    #: of writing "never" that would take a decade to notice was wrong.
    maximum: int
    #: What zero means, for the interface to say out loud.
    zero: str


DEFINITIONS: dict[str, Definition] = {
    definition.name: definition
    for definition in (
        Definition(
            name="trashRetentionDays",
            field="trash_retention_days",
            maximum=3650,
            zero="never",
        ),
        Definition(
            name="activityRetentionDays",
            field="activity_retention_days",
            maximum=3650,
            zero="never",
        ),
        Definition(
            name="uploadRetentionHours",
            field="upload_retention_hours",
            maximum=8760,
            zero="never",
        ),
    )
}


def default(settings: Settings, name: str) -> int:
    """Return what the deployment configured for ``name``."""
    return int(getattr(settings, DEFINITIONS[name].field))


def _validate(name: str, value: object) -> int:
    definition = DEFINITIONS.get(name)
    if definition is None:
        raise NotFoundError(f"No setting called '{name}'")

    # A bool is an int in Python and would store as 0 or 1, which is a period
    # of no days rather than the mistake it is.
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidInputError(f"'{name}' is a whole number of periods")
    if value < 0:
        raise InvalidInputError(f"'{name}' cannot be negative")
    if value > definition.maximum:
        raise InvalidInputError(f"'{name}' cannot be more than {definition.maximum}")
    return value


async def _stored(session: AsyncSession) -> dict[str, int]:
    """Return the settings somebody has changed, by name."""
    rows = await session.scalars(select(InstanceSetting))
    stored: dict[str, int] = {}
    for row in rows:
        if row.name not in DEFINITIONS:
            # A setting this version does not know about: an older row, or a
            # newer one after a downgrade. Left alone rather than deleted.
            continue
        try:
            stored[row.name] = _validate(row.name, json.loads(row.value))
        except ValueError, InvalidInputError, NotFoundError:
            # A row that cannot be read is not a reason to refuse the screen
            # that would let somebody fix it. The configured default stands.
            continue
    return stored


async def read_all(session: AsyncSession, settings: Settings) -> dict[str, int]:
    """Return every setting in force, stored or configured."""
    stored = await _stored(session)
    return {name: stored.get(name, default(settings, name)) for name in DEFINITIONS}


async def save(
    session: AsyncSession, settings: Settings, values: dict[str, object]
) -> dict[str, int]:
    """Store the settings in ``values`` and return every one in force.

    Every value is validated before any is written, so a request naming three
    settings and misspelling one changes nothing rather than half of it.
    """
    checked = {name: _validate(name, value) for name, value in values.items()}

    for name, value in checked.items():
        row = await session.get(InstanceSetting, name)
        if row is None:
            session.add(InstanceSetting(name=name, value=json.dumps(value)))
        else:
            row.value = json.dumps(value)

    await session.commit()
    return await read_all(session, settings)


async def clear(session: AsyncSession, name: str) -> None:
    """Forget a stored setting, returning it to what the deployment configured."""
    row = await session.get(InstanceSetting, name)
    if row is not None:
        await session.delete(row)
        await session.commit()
