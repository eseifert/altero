"""OAuth 2.0 and PKCE service operations."""

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, NotFoundError
from altero.models.oauth import OAuthAuthorizationCode, OAuthClient, OAuthToken
from altero.models.library import User


def hash_token(token: str) -> str:
    """Return the SHA-256 hex digest of a token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_token(nbytes: int = 32) -> str:
    """Return a URL-safe random string."""
    return secrets.token_urlsafe(nbytes)


def verify_pkce(code_verifier: str, code_challenge: str, method: str = "S256") -> bool:
    """Verify PKCE code_verifier against code_challenge."""
    if method == "plain":
        return secrets.compare_digest(code_verifier, code_challenge)
    if method == "S256":
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        computed = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        target = code_challenge.rstrip("=")
        return secrets.compare_digest(computed, target)
    return False


async def get_or_create_client(
    session: AsyncSession,
    client_id: str,
    client_name: str = "AltCanvas",
    redirect_uri: str = ""
) -> OAuthClient:
    """Ensure client registration exists."""
    client = await session.scalar(
        select(OAuthClient).where(OAuthClient.client_id == client_id)
    )
    if client is None:
        client = OAuthClient(
            client_id=client_id,
            client_name=client_name,
            redirect_uris=redirect_uri,
            allowed_scopes="openid profile library.read library.write annotations.read annotations.write files.read",
            is_confidential=False,
        )
        session.add(client)
        await session.commit()
    return client


async def create_authorization_code(
    session: AsyncSession,
    client_id: str,
    user_id: int,
    redirect_uri: str,
    scopes: str,
    code_challenge: str,
    code_challenge_method: str = "S256",
    nonce: str | None = None,
) -> str:
    """Issue a single-use authorization code expiring in 60 seconds."""
    raw_code = generate_token(32)
    code_h = hash_token(raw_code)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    expires = now + timedelta(seconds=60)

    auth_code = OAuthAuthorizationCode(
        code_hash=code_h,
        client_id=client_id,
        user_id=user_id,
        redirect_uri=redirect_uri,
        scopes=scopes,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        nonce=nonce,
        expires_at=expires,
    )
    session.add(auth_code)
    await session.commit()
    return raw_code


async def exchange_code_for_tokens(
    session: AsyncSession,
    client_id: str,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> dict[str, Any]:
    """Exchange authorization code for access and refresh tokens."""
    code_h = hash_token(code)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    row = await session.scalar(
        select(OAuthAuthorizationCode).where(
            and_(
                OAuthAuthorizationCode.code_hash == code_h,
                OAuthAuthorizationCode.client_id == client_id,
            )
        )
    )
    if row is None:
        raise ForbiddenError("Invalid authorization code")

    if row.consumed_at is not None:
        raise ForbiddenError("Authorization code has already been used")

    if row.expires_at < now:
        raise ForbiddenError("Authorization code has expired")

    # Mark consumed immediately
    row.consumed_at = now

    # Verify redirect_uri and PKCE verifier
    if row.redirect_uri != redirect_uri:
        raise ForbiddenError("Redirect URI mismatch")

    if not verify_pkce(code_verifier, row.code_challenge, row.code_challenge_method):
        raise ForbiddenError("Invalid PKCE code_verifier")

    # Fetch user for metadata
    user = await session.scalar(select(User).where(User.id == row.user_id))
    if user is None or user.disabled_at is not None:
        raise ForbiddenError("User account is inactive")

    # Generate tokens
    access_token_raw = generate_token(32)
    refresh_token_raw = generate_token(48)
    family_id = generate_token(16)

    access_expires = now + timedelta(seconds=3600)
    refresh_expires = now + timedelta(days=30)

    access_token_obj = OAuthToken(
        token_type="access",
        token_hash=hash_token(access_token_raw),
        family_id=family_id,
        client_id=client_id,
        user_id=row.user_id,
        scopes=row.scopes,
        expires_at=access_expires,
    )
    refresh_token_obj = OAuthToken(
        token_type="refresh",
        token_hash=hash_token(refresh_token_raw),
        family_id=family_id,
        client_id=client_id,
        user_id=row.user_id,
        scopes=row.scopes,
        expires_at=refresh_expires,
    )

    session.add(access_token_obj)
    session.add(refresh_token_obj)
    await session.commit()

    return {
        "access_token": access_token_raw,
        "token_type": "Bearer",
        "expires_in": 3600,
        "refresh_token": refresh_token_raw,
        "scope": row.scopes,
        "user_id": str(row.user_id),
        "username": user.username,
        "display_name": user.display_name or user.username,
    }


async def refresh_tokens(
    session: AsyncSession,
    client_id: str,
    refresh_token_str: str,
) -> dict[str, Any]:
    """Rotate refresh token and issue a new access token with reuse detection."""
    token_h = hash_token(refresh_token_str)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    token_obj = await session.scalar(
        select(OAuthToken).where(
            and_(
                OAuthToken.token_hash == token_h,
                OAuthToken.token_type == "refresh",
                OAuthToken.client_id == client_id,
            )
        )
    )
    if token_obj is None:
        raise ForbiddenError("Invalid refresh token")

    # Reuse detection: if already revoked, revoke whole token family
    if token_obj.revoked_at is not None:
        if token_obj.family_id:
            tokens_in_family = (
                await session.scalars(
                    select(OAuthToken).where(OAuthToken.family_id == token_obj.family_id)
                )
            ).all()
            for t in tokens_in_family:
                t.revoked_at = now
            await session.commit()
        raise ForbiddenError("Revoked refresh token reuse detected; entire token family invalidated")

    if token_obj.expires_at < now:
        raise ForbiddenError("Refresh token has expired")

    # Invalidate current refresh token
    token_obj.revoked_at = now

    user = await session.scalar(select(User).where(User.id == token_obj.user_id))
    if user is None or user.disabled_at is not None:
        raise ForbiddenError("User account is inactive")

    # Issue new pair in the same family
    new_access_raw = generate_token(32)
    new_refresh_raw = generate_token(48)

    access_expires = now + timedelta(seconds=3600)
    refresh_expires = now + timedelta(days=30)

    new_access_obj = OAuthToken(
        token_type="access",
        token_hash=hash_token(new_access_raw),
        family_id=token_obj.family_id,
        client_id=client_id,
        user_id=token_obj.user_id,
        scopes=token_obj.scopes,
        expires_at=access_expires,
    )
    new_refresh_obj = OAuthToken(
        token_type="refresh",
        token_hash=hash_token(new_refresh_raw),
        family_id=token_obj.family_id,
        client_id=client_id,
        user_id=token_obj.user_id,
        scopes=token_obj.scopes,
        expires_at=refresh_expires,
    )

    session.add(new_access_obj)
    session.add(new_refresh_obj)
    await session.commit()

    return {
        "access_token": new_access_raw,
        "token_type": "Bearer",
        "expires_in": 3600,
        "refresh_token": new_refresh_raw,
        "scope": token_obj.scopes,
        "user_id": str(token_obj.user_id),
        "username": user.username,
        "display_name": user.display_name or user.username,
    }


async def revoke_token(
    session: AsyncSession,
    client_id: str,
    token_str: str,
) -> bool:
    """Revoke an access or refresh token."""
    token_h = hash_token(token_str)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    token_obj = await session.scalar(
        select(OAuthToken).where(
            and_(
                OAuthToken.token_hash == token_h,
                OAuthToken.client_id == client_id,
            )
        )
    )
    if token_obj is None:
        return False

    token_obj.revoked_at = now
    if token_obj.token_type == "refresh" and token_obj.family_id:
        tokens_in_family = (
            await session.scalars(
                select(OAuthToken).where(OAuthToken.family_id == token_obj.family_id)
            )
        ).all()
        for t in tokens_in_family:
            t.revoked_at = now

    await session.commit()
    return True


async def validate_access_token(
    session: AsyncSession,
    access_token_str: str,
) -> OAuthToken | None:
    """Validate access token from bearer header."""
    token_h = hash_token(access_token_str)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    token_obj = await session.scalar(
        select(OAuthToken).where(
            and_(
                OAuthToken.token_hash == token_h,
                OAuthToken.token_type == "access",
                OAuthToken.revoked_at.is_(None),
                OAuthToken.expires_at > now,
            )
        )
    )
    return token_obj
