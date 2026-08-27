"""OAuth 2.0 and OpenID Connect data models."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from altero.db import Base


class OAuthClient(Base):
    """An OAuth 2.0 confidential or public client registration."""

    __tablename__ = "oauth_clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    client_secret_hash: Mapped[str | None] = mapped_column(String(128), default=None)
    client_name: Mapped[str] = mapped_column(String(128), default="")
    redirect_uris: Mapped[str] = mapped_column(Text, default="")
    allowed_scopes: Mapped[str] = mapped_column(
        String(255),
        default="openid profile library.read library.write annotations.read annotations.write files.read"
    )
    is_confidential: Mapped[bool] = mapped_column(Boolean, default=False)
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class OAuthAuthorizationCode(Base):
    """An issued one-time authorization code with PKCE."""

    __tablename__ = "oauth_authorization_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    client_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    redirect_uri: Mapped[str] = mapped_column(String(500))
    scopes: Mapped[str] = mapped_column(String(255))
    code_challenge: Mapped[str] = mapped_column(String(128))
    code_challenge_method: Mapped[str] = mapped_column(String(16), default="S256")
    nonce: Mapped[str | None] = mapped_column(String(128), default=None)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class OAuthToken(Base):
    """Access and refresh tokens issued to clients."""

    __tablename__ = "oauth_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_type: Mapped[str] = mapped_column(String(16))  # 'access' or 'refresh'
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    family_id: Mapped[str | None] = mapped_column(String(64), index=True)
    client_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    scopes: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
