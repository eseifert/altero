"""Account settings, notifications and invitations over HTTP."""

from datetime import UTC, datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import User, WebSession
from altero.services import (
    account,
    admin,
    invitations,
    reauth,
    totp,
    webauth,
    websessions,
)
from tests.test_web_routes import CSRF_HEADER, csrf_headers, register

PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "a quite different long password"


def _now() -> int:
    return int(datetime.now(UTC).timestamp())


class TestReadingTheAccount:
    async def test_it_reports_the_user_and_their_sessions(self, client: httpx.AsyncClient) -> None:
        await register(client)

        body = (await client.get("/web/account")).json()

        assert body["user"]["username"] == "ada"
        assert body["totpEnabled"] is False
        assert len(body["sessions"]) == 1
        assert body["sessions"][0]["current"] is True

    async def test_it_needs_a_session(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/web/account")).status_code == 401


class TestChangingThings:
    async def test_the_display_name_changes(self, client: httpx.AsyncClient) -> None:
        await register(client)

        response = await client.patch(
            "/web/account", json={"displayName": "Ada L."}, headers=csrf_headers(client)
        )

        assert response.status_code == 200
        assert response.json()["user"]["displayName"] == "Ada L."

    async def test_a_change_without_the_csrf_token_is_refused(
        self, client: httpx.AsyncClient
    ) -> None:
        await register(client)

        assert (await client.patch("/web/account", json={"displayName": "x"})).status_code == 403

    async def test_the_password_changes_with_the_current_one(
        self, client: httpx.AsyncClient
    ) -> None:
        await register(client)

        response = await client.post(
            "/web/account/password",
            json={"currentPassword": PASSWORD, "newPassword": NEW_PASSWORD},
            headers=csrf_headers(client),
        )

        assert response.status_code == 204
        # This browser stays signed in; the change did not sign it out.
        assert (await client.get("/web/account")).status_code == 200

    async def test_the_wrong_current_password_is_refused(self, client: httpx.AsyncClient) -> None:
        """A cookie alone must not be enough to replace the password."""
        await register(client)

        response = await client.post(
            "/web/account/password",
            json={"currentPassword": "not it", "newPassword": NEW_PASSWORD},
            headers=csrf_headers(client),
        )

        assert response.status_code == 403

    async def test_changing_the_address_does_not_change_it_yet(
        self, client: httpx.AsyncClient
    ) -> None:
        await register(client)

        response = await client.post(
            "/web/account/email",
            json={"email": "new@example.org", "currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        assert response.status_code == 202
        assert (await client.get("/web/account")).json()["user"]["email"] == "ada@example.org"

    async def test_changing_the_address_needs_the_password(self, client: httpx.AsyncClient) -> None:
        await register(client)

        response = await client.post(
            "/web/account/email",
            json={"email": "new@example.org", "currentPassword": "not it"},
            headers=csrf_headers(client),
        )

        assert response.status_code == 403


class TestTheSecondFactor:
    async def test_enrolment_is_two_steps(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)

        started = await client.post("/web/account/totp", headers=csrf_headers(client))
        assert started.status_code == 201
        secret = started.json()["secret"]
        assert started.json()["uri"].startswith("otpauth://totp/altero:ada?")

        # Not yet in force.
        assert (await client.get("/web/account")).json()["totpEnabled"] is False

        confirmed = await client.post(
            "/web/account/totp/confirm",
            json={"code": totp.code_at(secret, _now())},
            headers=csrf_headers(client),
        )
        assert confirmed.status_code == 204
        assert (await client.get("/web/account")).json()["totpEnabled"] is True

    async def test_a_wrong_confirmation_code_leaves_it_off(self, client: httpx.AsyncClient) -> None:
        await register(client)
        await client.post("/web/account/totp", headers=csrf_headers(client))

        response = await client.post(
            "/web/account/totp/confirm", json={"code": "000000"}, headers=csrf_headers(client)
        )

        assert response.status_code == 403
        assert (await client.get("/web/account")).json()["totpEnabled"] is False

    async def test_disabling_needs_the_password(self, client: httpx.AsyncClient) -> None:
        await register(client)
        started = await client.post("/web/account/totp", headers=csrf_headers(client))
        await client.post(
            "/web/account/totp/confirm",
            json={"code": totp.code_at(started.json()["secret"], _now())},
            headers=csrf_headers(client),
        )

        refused = await client.post(
            "/web/account/totp/disable",
            json={"currentPassword": "not it"},
            headers=csrf_headers(client),
        )
        assert refused.status_code == 403
        assert (await client.get("/web/account")).json()["totpEnabled"] is True

        allowed = await client.post(
            "/web/account/totp/disable",
            json={"currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )
        assert allowed.status_code == 204
        assert (await client.get("/web/account")).json()["totpEnabled"] is False


class TestSessions:
    async def test_signing_out_everywhere_else_keeps_this_one(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        user = await admin.get_user_by_name(session, "ada")
        from altero.services import websessions

        await websessions.create(session, user, user_agent="another browser")

        response = await client.post(
            "/web/account/sessions/revoke-others", headers=csrf_headers(client)
        )

        assert response.status_code == 204
        assert len((await client.get("/web/account")).json()["sessions"]) == 1

    async def test_another_account_s_session_cannot_be_ended(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        grace = await webauth.register(
            session,
            username="grace",
            password=PASSWORD,
            email="grace@example.org",
            allow_registration=True,
        )
        from altero.services import websessions

        _, theirs = await websessions.create(session, grace)

        response = await client.delete(
            f"/web/account/sessions/{theirs.id}", headers=csrf_headers(client)
        )

        assert response.status_code == 403


class TestNotificationsAndInvitations:
    async def test_an_invitation_arrives_as_a_notification(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The point of the in-app list: it does not depend on mail working."""
        await register(client)
        ada = await admin.get_user_by_name(session, "ada")
        grace = await webauth.register(
            session,
            username="grace",
            password=PASSWORD,
            email="grace@example.org",
            allow_registration=True,
        )
        library = await admin.create_group(
            session, name="Analytical Engine", owner_username="grace"
        )
        await invitations.invite(session, library=library, inviter=grace, email="ada@example.org")

        body = (await client.get("/web/notifications")).json()

        assert body["unread"] == 1
        assert body["notifications"][0]["kind"] == "invitation"
        assert len(body["invitations"]) == 1
        assert body["invitations"][0]["libraryName"] == "Analytical Engine"
        assert ada.id

    async def test_accepting_joins_the_group_and_clears_the_badge(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        grace = await webauth.register(
            session,
            username="grace",
            password=PASSWORD,
            email="grace@example.org",
            allow_registration=True,
        )
        library = await admin.create_group(
            session, name="Analytical Engine", owner_username="grace"
        )
        invitation = await invitations.invite(
            session, library=library, inviter=grace, email="ada@example.org"
        )

        response = await client.post(
            f"/web/invitations/{invitation.id}/accept", headers=csrf_headers(client)
        )

        assert response.status_code == 200
        assert response.json()["invitation"]["status"] == "accepted"
        assert (await client.get("/web/notifications")).json()["unread"] == 0
        # And the group library is now visible.
        assert len((await client.get("/web/libraries")).json()) == 2

    async def test_declining_does_not_join(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        grace = await webauth.register(
            session,
            username="grace",
            password=PASSWORD,
            email="grace@example.org",
            allow_registration=True,
        )
        library = await admin.create_group(
            session, name="Analytical Engine", owner_username="grace"
        )
        invitation = await invitations.invite(
            session, library=library, inviter=grace, email="ada@example.org"
        )

        response = await client.post(
            f"/web/invitations/{invitation.id}/decline", headers=csrf_headers(client)
        )

        assert response.status_code == 200
        assert len((await client.get("/web/libraries")).json()) == 1

    async def test_somebody_else_s_invitation_cannot_be_accepted(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        grace = await webauth.register(
            session,
            username="grace",
            password=PASSWORD,
            email="grace@example.org",
            allow_registration=True,
        )
        library = await admin.create_group(
            session, name="Analytical Engine", owner_username="grace"
        )
        invitation = await invitations.invite(
            session, library=library, inviter=grace, email="somebody@example.org"
        )

        response = await client.post(
            f"/web/invitations/{invitation.id}/accept", headers=csrf_headers(client)
        )

        assert response.status_code == 403

    async def test_marking_all_read_clears_the_badge(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        from altero.services import notifications

        ada = await admin.get_user_by_name(session, "ada")
        await notifications.raise_for(session, ada, kind="security", subject="Something")

        await client.post("/web/notifications/read-all", headers=csrf_headers(client))

        assert (await client.get("/web/notifications")).json()["unread"] == 0

    async def test_an_admin_can_invite_through_the_api(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        library = await admin.create_group(session, name="Analytical Engine", owner_username="ada")
        await webauth.register(
            session,
            username="grace",
            password=PASSWORD,
            email="grace@example.org",
            allow_registration=True,
        )

        response = await client.post(
            f"/web/libraries/{library.id}/invitations",
            json={"email": "grace@example.org", "role": "admin"},
            headers=csrf_headers(client),
        )

        assert response.status_code == 201
        assert response.json()["invitation"]["role"] == "admin"

        listed = await client.get(f"/web/libraries/{library.id}/invitations")
        assert len(listed.json()["invitations"]) == 1

    async def test_a_non_admin_cannot_invite(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        grace = await webauth.register(
            session,
            username="grace",
            password=PASSWORD,
            email="grace@example.org",
            allow_registration=True,
        )
        library = await admin.create_group(session, name="Theirs", owner_username="grace")

        response = await client.post(
            f"/web/libraries/{library.id}/invitations",
            json={"email": "x@example.org"},
            headers=csrf_headers(client),
        )

        assert response.status_code == 403
        assert grace.id

    async def test_answering_an_invitation_needs_the_csrf_token(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        grace = await webauth.register(
            session,
            username="grace",
            password=PASSWORD,
            email="grace@example.org",
            allow_registration=True,
        )
        library = await admin.create_group(
            session, name="Analytical Engine", owner_username="grace"
        )
        invitation = await invitations.invite(
            session, library=library, inviter=grace, email="ada@example.org"
        )

        response = await client.post(f"/web/invitations/{invitation.id}/accept")

        assert response.status_code == 403
        assert CSRF_HEADER

    async def test_notifications_need_a_session(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/web/notifications")).status_code == 401


class TestTheV3ApiIsStillUntouched:
    async def test_a_cookie_does_not_reach_the_sync_api(self, client: httpx.AsyncClient) -> None:
        """Repeated here because this file adds a lot of new cookie endpoints."""
        await register(client)
        await client.post("/web/account/totp", headers=csrf_headers(client))

        assert (await client.get("/users/1/items")).status_code == 403

    async def test_an_api_key_does_not_reach_the_account_endpoints(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        key = await admin.create_api_key(session, username="ada", name="laptop")
        client.cookies.clear()

        response = await client.get("/web/account", headers={"Zotero-API-Key": key.key})

        assert response.status_code == 401
        assert account.TOTP_ISSUER == "altero"


class TestManagingKeys:
    async def test_a_new_account_has_none(self, client: httpx.AsyncClient) -> None:
        await register(client)

        assert (await client.get("/web/account/keys")).json() == {"keys": []}

    async def test_creating_returns_the_key_once(self, client: httpx.AsyncClient) -> None:
        await register(client)

        response = await client.post(
            "/web/account/keys",
            json={"name": "laptop", "currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        assert response.status_code == 201
        assert len(response.json()["key"]) >= 20
        assert response.json()["created"]["name"] == "laptop"

    async def test_the_list_never_shows_the_key_again(self, client: httpx.AsyncClient) -> None:
        """Otherwise a signed-in tab is a way to read back every credential."""
        await register(client)
        created = await client.post(
            "/web/account/keys",
            json={"name": "laptop", "currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )
        key = created.json()["key"]

        listed = (await client.get("/web/account/keys")).json()["keys"]

        assert key not in str(listed)
        assert listed[0]["suffix"] == key[-4:]

    async def test_creating_needs_the_password(self, client: httpx.AsyncClient) -> None:
        await register(client)

        response = await client.post(
            "/web/account/keys",
            json={"name": "laptop", "currentPassword": "not it"},
            headers=csrf_headers(client),
        )

        assert response.status_code == 403
        assert (await client.get("/web/account/keys")).json()["keys"] == []

    async def test_creating_needs_the_csrf_token(self, client: httpx.AsyncClient) -> None:
        await register(client)

        response = await client.post(
            "/web/account/keys", json={"name": "laptop", "currentPassword": PASSWORD}
        )

        assert response.status_code == 403

    async def test_the_key_it_issues_works(self, client: httpx.AsyncClient) -> None:
        await register(client)
        created = await client.post(
            "/web/account/keys",
            json={"name": "laptop", "currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        response = await client.get(
            "/users/1/items", headers={"Zotero-API-Key": created.json()["key"]}
        )

        assert response.status_code == 200

    async def test_a_read_only_key_cannot_write(self, client: httpx.AsyncClient) -> None:
        await register(client)
        created = await client.post(
            "/web/account/keys",
            json={"name": "a script", "currentPassword": PASSWORD, "write": False},
            headers=csrf_headers(client),
        )
        key = created.json()["key"]

        assert (
            await client.get("/users/1/items", headers={"Zotero-API-Key": key})
        ).status_code == 200
        assert (
            await client.post(
                "/users/1/items",
                headers={"Zotero-API-Key": key},
                json=[{"itemType": "book", "title": "Nope"}],
            )
        ).status_code == 403

    async def test_revoking_stops_it_working(self, client: httpx.AsyncClient) -> None:
        await register(client)
        created = await client.post(
            "/web/account/keys",
            json={"name": "laptop", "currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )
        key = created.json()["key"]
        key_id = created.json()["created"]["id"]

        response = await client.delete(f"/web/account/keys/{key_id}", headers=csrf_headers(client))

        assert response.status_code == 204
        assert (
            await client.get("/users/1/items", headers={"Zotero-API-Key": key})
        ).status_code == 403

    async def test_revoking_needs_no_password(self, client: httpx.AsyncClient) -> None:
        """A key is revoked at the moment it has leaked; do not ask for more."""
        await register(client)
        created = await client.post(
            "/web/account/keys",
            json={"name": "laptop", "currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        response = await client.delete(
            f"/web/account/keys/{created.json()['created']['id']}",
            headers=csrf_headers(client),
        )

        assert response.status_code == 204

    async def test_another_account_s_key_cannot_be_revoked(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        await webauth.register(
            session,
            username="grace",
            password=PASSWORD,
            email="grace@example.org",
            allow_registration=True,
        )
        theirs = await admin.create_api_key(session, username="grace", name="theirs")

        response = await client.delete(
            f"/web/account/keys/{theirs.id}", headers=csrf_headers(client)
        )

        assert response.status_code == 403

    async def test_the_key_from_linking_a_client_shows_up_here(
        self, client: httpx.AsyncClient
    ) -> None:
        """The two ways of getting a key end up in the same list."""
        await register(client)
        token = (await client.post("/keys/sessions", json={})).json()["sessionToken"]
        await client.post(
            f"/web/link/{token}/approve",
            json={"currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        listed = (await client.get("/web/account/keys")).json()["keys"]

        assert [entry["name"] for entry in listed] == ["Zotero client"]

    async def test_keys_need_a_session(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/web/account/keys")).status_code == 401

    async def test_a_new_key_reports_never_used(self, client: httpx.AsyncClient) -> None:
        await register(client)
        await client.post(
            "/web/account/keys",
            json={"name": "laptop", "currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        listed = (await client.get("/web/account/keys")).json()["keys"]

        assert listed[0]["lastUsed"] is None
        assert listed[0]["lastAddress"] is None

    async def test_using_a_key_shows_up_in_the_list(self, client: httpx.AsyncClient) -> None:
        """This is what makes the list answer "which can I revoke?"."""
        await register(client)
        created = await client.post(
            "/web/account/keys",
            json={"name": "laptop", "currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        await client.get(
            "/users/1/items",
            headers={"Zotero-API-Key": created.json()["key"], "User-Agent": "Zotero/7.0"},
        )

        listed = (await client.get("/web/account/keys")).json()["keys"]
        assert listed[0]["lastUsed"] is not None
        assert listed[0]["lastUserAgent"] == "Zotero/7.0"


class TestLanguageAndTimeZone:
    """Both are account settings, so they follow the person between browsers."""

    async def test_a_new_account_follows_the_browser(self, client: httpx.AsyncClient) -> None:
        """Null is the setting, not the absence of one."""
        await register(client)

        body = (await client.get("/web/account")).json()

        assert body["user"]["language"] is None
        assert body["user"]["timeZone"] is None

    async def test_both_are_set_together(self, client: httpx.AsyncClient) -> None:
        await register(client)

        response = await client.put(
            "/web/account/locale",
            headers=csrf_headers(client),
            json={"language": "de", "timeZone": "Europe/Berlin"},
        )

        assert response.status_code == 200
        assert response.json()["user"]["language"] == "de"
        assert response.json()["user"]["timeZone"] == "Europe/Berlin"

    async def test_the_setting_outlives_the_session(self, client: httpx.AsyncClient) -> None:
        await register(client)
        await client.put(
            "/web/account/locale",
            headers=csrf_headers(client),
            json={"language": "ja", "timeZone": "Asia/Tokyo"},
        )

        body = (await client.get("/web/account")).json()

        assert body["user"]["language"] == "ja"
        assert body["user"]["timeZone"] == "Asia/Tokyo"

    async def test_either_can_go_back_to_following_the_browser(
        self, client: httpx.AsyncClient
    ) -> None:
        await register(client)
        await client.put(
            "/web/account/locale",
            headers=csrf_headers(client),
            json={"language": "fr", "timeZone": "Europe/Paris"},
        )

        await client.put(
            "/web/account/locale",
            headers=csrf_headers(client),
            json={"language": None, "timeZone": None},
        )

        body = (await client.get("/web/account")).json()
        assert body["user"]["language"] is None
        assert body["user"]["timeZone"] is None

    async def test_a_region_narrows_to_the_language_it_has_a_catalogue_for(
        self, client: httpx.AsyncClient
    ) -> None:
        """`pt-BR` is Portuguese as far as the interface strings go. The region
        still reaches date formatting, which the browser supplies separately."""
        await register(client)

        response = await client.put(
            "/web/account/locale",
            headers=csrf_headers(client),
            json={"language": "pt-BR", "timeZone": "America/Sao_Paulo"},
        )

        assert response.json()["user"]["language"] == "pt"

    async def test_a_language_with_no_catalogue_is_refused(self, client: httpx.AsyncClient) -> None:
        await register(client)

        response = await client.put(
            "/web/account/locale", headers=csrf_headers(client), json={"language": "kl"}
        )

        assert response.status_code == 400

    async def test_a_time_zone_the_server_does_not_know_is_refused(
        self, client: httpx.AsyncClient
    ) -> None:
        """Offered from the server's own database, so anything else is a typo
        or a client inventing zones."""
        await register(client)

        response = await client.put(
            "/web/account/locale", headers=csrf_headers(client), json={"timeZone": "Mars/Olympus"}
        )

        assert response.status_code == 400

    async def test_a_utc_offset_is_not_a_time_zone(self, client: httpx.AsyncClient) -> None:
        """An offset is wrong for half the year anywhere that keeps summer time."""
        await register(client)

        response = await client.put(
            "/web/account/locale", headers=csrf_headers(client), json={"timeZone": "+02:00"}
        )

        assert response.status_code == 400

    async def test_setting_it_needs_the_csrf_token(self, client: httpx.AsyncClient) -> None:
        await register(client)

        response = await client.put("/web/account/locale", json={"language": "de"})

        assert response.status_code == 403

    async def test_the_choices_come_from_the_server(self, client: httpx.AsyncClient) -> None:
        await register(client)

        body = (await client.get("/web/account/locales")).json()

        assert {entry["tag"] for entry in body["languages"]} == {"en", "de", "fr", "es", "pt", "ja"}
        assert "Europe/Berlin" in body["timeZones"]
        assert len(body["timeZones"]) > 100


class TestAnAccountWithNoPassword:
    """The accounts single sign-on will create, and the ones `altero user add` makes.

    Every one of these operations used to ask for a password and refuse anyone
    who had none, which would have made a federated account able to sign in and
    then do nothing at all -- including issue itself the API key a desktop
    client needs. See `altero.services.reauth`.
    """

    async def _signed_in(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> tuple[User, WebSession]:
        """Make a passwordless account and put its cookie in ``client``."""
        # The first account made on an instance administers it, and this test
        # is about an ordinary one; registering first takes that flag.
        await register(client)
        user = await admin.create_user(session, username="grace", display_name="Grace")
        token, record = await websessions.create(session, user, user_agent="tests")
        client.cookies.set("altero_session", token)
        return user, record

    async def test_it_cannot_make_a_key_without_proving_itself(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await self._signed_in(client, session)

        response = await client.post(
            "/web/account/keys", json={"name": "Zotero"}, headers=csrf_headers(client)
        )

        assert response.status_code == 403

    async def test_a_recent_proof_lets_it_make_one(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        _, record = await self._signed_in(client, session)
        await reauth.stamp(session, record)

        response = await client.post(
            "/web/account/keys", json={"name": "Zotero"}, headers=csrf_headers(client)
        )

        assert response.status_code == 201
        assert response.json()["key"]

    async def test_a_made_up_password_does_not_get_it_through(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """There is no hash to match, and `verify_password` must not say yes."""
        await self._signed_in(client, session)

        response = await client.post(
            "/web/account/keys",
            json={"name": "Zotero", "currentPassword": "anything at all"},
            headers=csrf_headers(client),
        )

        assert response.status_code == 403

    async def test_it_can_set_a_password_once_it_has_proved_itself(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        _, record = await self._signed_in(client, session)
        await reauth.stamp(session, record)

        response = await client.post(
            "/web/account/password",
            json={"newPassword": NEW_PASSWORD},
            headers=csrf_headers(client),
        )

        assert response.status_code == 204


class TestAPasswordIsStillAskedFor:
    async def test_making_a_key_without_one_is_refused(self, client: httpx.AsyncClient) -> None:
        """An ordinary account gains nothing from the new seam."""
        await register(client)

        response = await client.post(
            "/web/account/keys", json={"name": "Zotero"}, headers=csrf_headers(client)
        )

        assert response.status_code == 403

    async def test_the_wrong_one_is_refused(self, client: httpx.AsyncClient) -> None:
        await register(client)

        response = await client.post(
            "/web/account/keys",
            json={"name": "Zotero", "currentPassword": "not it"},
            headers=csrf_headers(client),
        )

        assert response.status_code == 403

    async def test_giving_it_once_covers_the_next_operation(
        self, client: httpx.AsyncClient
    ) -> None:
        """What the freshness window is for: a settings page asks once."""
        await register(client)

        first = await client.post(
            "/web/account/keys",
            json={"name": "Zotero", "currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )
        second = await client.post(
            "/web/account/keys", json={"name": "A second one"}, headers=csrf_headers(client)
        )

        assert first.status_code == 201
        assert second.status_code == 201
