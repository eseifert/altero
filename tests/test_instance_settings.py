"""Policies that belong to the operator.

Two sources with an order between them: a stored row wins, and where there is
none the deployment's own configuration supplies the value. That is what lets
an operator keep `config.py` and still see their own numbers on the screen.
"""

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import InvalidInputError, NotFoundError
from altero.services import instancesettings
from altero.settings import Settings
from tests.test_web_routes import csrf_headers, register


class TestWhereAValueComesFrom:
    async def test_an_unset_setting_falls_back_to_the_configuration(
        self, session: AsyncSession
    ) -> None:
        settings = Settings(trash_retention_days=30)

        values = await instancesettings.read_all(session, settings)

        assert values["trashRetentionDays"] == 30

    async def test_a_stored_value_wins(self, session: AsyncSession) -> None:
        settings = Settings(trash_retention_days=30)

        await instancesettings.save(session, settings, {"trashRetentionDays": 7})

        assert (await instancesettings.read_all(session, settings))["trashRetentionDays"] == 7

    async def test_clearing_one_returns_it_to_the_configuration(
        self, session: AsyncSession
    ) -> None:
        """Rather than to a number this module invented."""
        settings = Settings(trash_retention_days=30)
        await instancesettings.save(session, settings, {"trashRetentionDays": 7})

        await instancesettings.clear(session, "trashRetentionDays")

        assert (await instancesettings.read_all(session, settings))["trashRetentionDays"] == 30

    async def test_a_fresh_instance_needs_no_rows(self, session: AsyncSession) -> None:
        values = await instancesettings.read_all(session, Settings())

        assert set(values) == set(instancesettings.DEFINITIONS)


class TestWhatIsRefused:
    """These are periods after which data is deleted, so nothing is guessed at."""

    async def test_an_unknown_setting(self, session: AsyncSession) -> None:
        with pytest.raises(NotFoundError):
            await instancesettings.save(session, Settings(), {"nonsense": 1})

    async def test_a_negative_period(self, session: AsyncSession) -> None:
        with pytest.raises(InvalidInputError):
            await instancesettings.save(session, Settings(), {"trashRetentionDays": -1})

    async def test_something_that_is_not_a_number(self, session: AsyncSession) -> None:
        with pytest.raises(InvalidInputError):
            await instancesettings.save(session, Settings(), {"trashRetentionDays": "thirty"})

    async def test_a_boolean(self, session: AsyncSession) -> None:
        """True is 1 in Python, which would be a period of one day."""
        with pytest.raises(InvalidInputError):
            await instancesettings.save(session, Settings(), {"trashRetentionDays": True})

    async def test_an_absurd_period(self, session: AsyncSession) -> None:
        with pytest.raises(InvalidInputError):
            await instancesettings.save(session, Settings(), {"trashRetentionDays": 100_000})

    async def test_nothing_is_stored_when_one_value_is_refused(self, session: AsyncSession) -> None:
        """A request naming three settings changes all of them or none."""
        settings = Settings()

        with pytest.raises(InvalidInputError):
            await instancesettings.save(
                session, settings, {"trashRetentionDays": 7, "activityRetentionDays": -5}
            )

        assert (await instancesettings.read_all(session, settings))["trashRetentionDays"] == 0


class TestThroughTheBrowser:
    async def test_an_administrator_reads_the_settings(self, client: httpx.AsyncClient) -> None:
        await register(client)

        body = (await client.get("/web/admin/settings")).json()

        assert body["settings"]["trashRetentionDays"] == 0

    async def test_an_administrator_changes_one(self, client: httpx.AsyncClient) -> None:
        await register(client)

        response = await client.put(
            "/web/admin/settings",
            json={"trashRetentionDays": 30},
            headers=csrf_headers(client),
        )

        assert response.status_code == 200
        assert response.json()["settings"]["trashRetentionDays"] == 30

    async def test_a_write_without_the_csrf_token_is_refused(
        self, client: httpx.AsyncClient
    ) -> None:
        await register(client)

        response = await client.put("/web/admin/settings", json={"trashRetentionDays": 30})

        assert response.status_code == 403

    async def test_a_refused_value_says_why(self, client: httpx.AsyncClient) -> None:
        await register(client)

        response = await client.put(
            "/web/admin/settings",
            json={"trashRetentionDays": -1},
            headers=csrf_headers(client),
        )

        assert response.status_code == 400
        assert "negative" in response.json()["message"]

    async def test_it_says_what_the_configuration_would_give(
        self, client: httpx.AsyncClient
    ) -> None:
        """So the screen can say a stored number is not the deployment's own."""
        await register(client)

        body = (await client.get("/web/admin/settings")).json()

        assert body["defaults"]["trashRetentionDays"] == 0
