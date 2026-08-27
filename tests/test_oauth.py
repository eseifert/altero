"""Tests for OAuth 2.0 and PKCE authentication endpoints."""

import base64
import hashlib
import secrets
import pytest
from httpx import ASGITransport, AsyncClient

from altero.app import create_app
from altero.services import admin, webauth
from altero.settings import get_settings


def create_pkce():
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


@pytest.mark.asyncio
async def test_openid_configuration(client):
    res = await client.get("/.well-known/openid-configuration")
    assert res.status_code == 200
    data = res.json()
    assert "oauth/authorize" in data["authorization_endpoint"]
    assert "oauth/token" in data["token_endpoint"]
    assert "S256" in data["code_challenge_methods_supported"]


@pytest.mark.asyncio
async def test_oauth_authorization_and_token_flow(client, session):
    # Create a test user
    user = await admin.create_user(session, username="oauthuser", display_name="OAuth User")
    await session.commit()
    await webauth.set_password(session, user, "CorrectPassword123!")

    verifier, challenge = create_pkce()
    redirect_uri = "http://localhost:8088/auth/callback"
    # 1. Authorize POST with credentials
    auth_res = await client.post(
        "/oauth/authorize",
        data={
            "client_id": "altcanvas",
            "redirect_uri": redirect_uri,
            "scope": "openid profile library.read library.write annotations.write files.read",
            "state": "randomstate123",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "username": "oauthuser",
            "password": "CorrectPassword123!",
        },
        follow_redirects=False,
    )
    assert auth_res.status_code == 302
    location = auth_res.headers["location"]
    assert redirect_uri in location
    assert "code=" in location
    assert "state=randomstate123" in location

    # Extract code
    code = location.split("code=")[1].split("&")[0]

    # 2. Exchange code with PKCE verifier
    token_res = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "altcanvas",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
        },
    )
    assert token_res.status_code == 200
    tokens = token_res.json()
    assert "access_token" in tokens
    assert "refresh_token" in tokens
    assert tokens["token_type"] == "Bearer"
    assert tokens["user_id"] == str(user.id)

    access_token = tokens["access_token"]
    refresh_token = tokens["refresh_token"]

    # 3. Access userinfo with Bearer token
    userinfo_res = await client.get(
        "/oauth/userinfo",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    assert userinfo_res.status_code == 200
    u_info = userinfo_res.json()
    assert u_info["username"] == "oauthuser"

    # 4. Access Zotero Library with Bearer token
    items_res = await client.get(
        f"/users/{user.id}/items/top",
        headers={"Authorization": f"Bearer {access_token}", "Zotero-API-Version": "3"}
    )
    assert items_res.status_code == 200

    # 5. Rotate Refresh Token
    refresh_res = await client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": "altcanvas",
            "refresh_token": refresh_token,
        },
    )
    assert refresh_res.status_code == 200
    new_tokens = refresh_res.json()
    assert new_tokens["access_token"] != access_token
    assert new_tokens["refresh_token"] != refresh_token

    # 6. Reuse Detection: trying old refresh token should fail with 403
    reuse_res = await client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": "altcanvas",
            "refresh_token": refresh_token,
        },
    )
    assert reuse_res.status_code == 403
