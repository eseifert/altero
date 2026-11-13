"""Passwordless SSO completes the ordinary library and SAML workflows."""

import httpx2
from fastapi import FastAPI
from lxml import etree  # ty: ignore[unresolved-import]
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_saml import CERTIFICATE, IDP, authn_request, signed
from tests.test_sso_only import enable
from tests.test_web_identity import (
    Directory,
    add_provider,
    reauthenticate,
    signed_in_through_the_directory,
)
from tests.test_web_identity import directory as directory
from tests.test_web_identity import settings as settings
from tests.test_web_migrate import SOURCE_KEY, settled
from tests.test_web_migrate import empty_register as empty_register
from tests.test_web_migrate import reachable as reachable
from tests.test_web_migrate import source as source
from tests.test_web_routes import csrf_headers, register


async def test_recent_sso_proof_can_migrate_with_only_the_separate_zotero_key(
    app: FastAPI,
    client: httpx2.AsyncClient,
    session: AsyncSession,
    directory: Directory,
    reachable: None,
) -> None:
    await signed_in_through_the_directory(client, directory, session)
    enable(app)
    body = {"apiKey": SOURCE_KEY}
    headers = csrf_headers(client)
    assert (await client.post("/web/migrate/zotero", json=body, headers=headers)).status_code == 403
    await reauthenticate(client, directory)
    response = await client.post("/web/migrate/zotero", json=body, headers=headers)
    assert response.status_code == 202, response.text
    done = await settled(client)
    assert done["stage"] == "done", done


async def test_saml_sign_in_and_force_authentication_work_in_sso_only_mode(
    app: FastAPI,
    client: httpx2.AsyncClient,
) -> None:
    await register(client)
    made = await add_provider(
        client,
        kind="saml",
        issuer=None,
        clientId=None,
        clientSecret=None,
        idpEntityId=IDP,
        certificates=CERTIFICATE,
        ssoUrl=f"{IDP}/saml",
        createAccounts=True,
    )
    assert made.status_code == 201
    client.cookies.clear()
    enable(app)
    for purpose in ("login", "reauth"):
        started = await client.get("/web/auth/sso/campus/start", params={"purpose": purpose})
        xml = authn_request(started.headers["location"])
        if purpose == "reauth":
            assert 'ForceAuthn="true"' in xml
        request_id = etree.fromstring(xml.encode()).get("ID")
        assertion = signed(
            issuer=IDP,
            audience="http://testserver",
            recipient="http://testserver/web/auth/saml/campus/acs",
            in_response_to=request_id,
            assertion_id=f"_assertion_{purpose}_0000000000000000000000001",
        )
        response = await client.post("/web/auth/saml/campus/acs", data={"SAMLResponse": assertion})
        assert response.status_code == 303
        response = await client.get(response.headers["location"])
        assert response.status_code == 303
        assert (await client.get("/web/auth/session")).status_code == 200
    assert (await client.get("/web/account/proof")).json()["fresh"] is True
