"""Letting somebody else's application read a library on its owner's behalf.

The other direction from :mod:`altero.models.identity`. There, altero is the
client and somebody else's directory says who a person is; here altero is the
authorization server and somebody else's application asks for a library. The
two share no tables and only the vocabulary.

Six tables, and the split between them is the point.

:class:`OAuthClient` is the operator's registration: which application, which
redirect URIs, which scopes it may ever ask for. An administrator creates it
from the command line. Nothing self-registers -- a redirect URI accepted
because it was presented is the hole that turns an authorization server into a
way of phishing its own users.

:class:`OAuthAuthorizationRequest` is an authorization part-way through
happening, in the database for the reason :class:`~altero.models.identity.AuthRequest`
is: signing in must not break when a deployment adds a second worker.

:class:`OAuthGrant` is the standing consent -- what this person has agreed this
application may do, which is what "Connected applications" lists and what
revoking removes. Codes and tokens hang off it, so revoking a grant takes every
credential issued under it with it.

:class:`OAuthCode` is one authorization code, hashed, single use, bound to the
PKCE challenge the request carried.

:class:`OAuthToken` is an access or refresh token, hashed, with the family a
rotated refresh token stays in so that a replayed one can burn the lot.

:class:`OAuthSigningKey` is the RSA key ID tokens are signed with. In the
database rather than on disk so that two workers, and a restored backup, agree
about it -- a client that cached the JWKS looks a ``kid`` up and has to find it.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from altero.db import Base


class OAuthClient(Base):
    """An application an administrator has registered.

    Registered rather than discovered. The redirect URIs are the whole security
    of the authorization code flow: the code is handed to the browser, and the
    only thing deciding it reaches the application rather than somebody else is
    that the address it goes to was written down here first.
    """

    __tablename__ = "oauth_clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: The public identifier, as the application sends it. Chosen by the
    #: administrator so it can be something a person recognises in a log.
    client_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    #: What the consent screen calls it. Shown to whoever is being asked to
    #: approve, so it is the name that has to be trustworthy, not the id.
    name: Mapped[str] = mapped_column(String(128), default="")
    #: Argon2 hash of the client secret, for a confidential client. ``None``
    #: means public: a browser or desktop application that cannot keep one, and
    #: is therefore held up by PKCE alone.
    secret_hash: Mapped[str | None] = mapped_column(String(255), default=None)
    #: Permitted redirect URIs, one per line, matched exactly -- with the one
    #: documented exception for loopback ports that RFC 8252 §7.3 requires for
    #: applications that listen on an ephemeral one.
    redirect_uris: Mapped[str] = mapped_column(Text, default="")
    #: The scopes this client may ever ask for, space separated. A ceiling: a
    #: request for more is refused rather than quietly narrowed, so an
    #: application discovers the misconfiguration instead of half working.
    scopes: Mapped[str] = mapped_column(String(255), default="openid")
    #: A short description of what the application does with the library, shown
    #: under the name on the consent screen.
    description: Mapped[str] = mapped_column(String(500), default="")
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    #: Set to stop the client working without losing the record of it, the same
    #: way an account is suspended rather than deleted.
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class OAuthAuthorizationRequest(Base):
    """An authorization between arriving at ``/oauth/authorize`` and being answered.

    Everything the application asked for, checked once when it arrived and then
    read from here rather than from the browser again. That is what stops the
    consent screen describing one request while the code is issued for another:
    the interface is handed an opaque handle and can change nothing behind it.
    """

    __tablename__ = "oauth_authorization_requests"

    #: The handle the interface carries, and the primary key. A handle that does
    #: not resolve is an authorization this server never started.
    handle: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("oauth_clients.id", ondelete="CASCADE"), index=True
    )
    #: Validated against the client's list when the request arrived, and used
    #: verbatim afterwards. Never re-read from a later request.
    redirect_uri: Mapped[str] = mapped_column(String(500))
    scopes: Mapped[str] = mapped_column(String(255), default="")
    #: The application's own state, echoed back untouched. Its CSRF defence,
    #: and none of this server's business beyond returning it.
    state: Mapped[str] = mapped_column(String(255), default="")
    #: PKCE. S256 only, so there is no method to record: a challenge that came
    #: with any other method was refused at the door.
    code_challenge: Mapped[str] = mapped_column(String(128), default="")
    #: Echoed into the ID token, pinning it to this request.
    nonce: Mapped[str] = mapped_column(String(255), default="")
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires: Mapped[datetime] = mapped_column(DateTime, index=True)


class OAuthGrant(Base):
    """What one person has agreed one application may do.

    Standing, so returning to an application that already has consent does not
    ask again for what was already given -- and asks properly when it wants
    more. It is also the handle a person revokes: codes and tokens cascade from
    here, so "disconnect this application" is one row going away.
    """

    __tablename__ = "oauth_grants"
    __table_args__ = (UniqueConstraint("user_id", "client_id", name="uq_oauth_grant"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("oauth_clients.id", ondelete="CASCADE"), index=True
    )
    #: Everything approved so far, space separated. Widened when a later
    #: request asks for more and is approved; never widened without asking.
    scopes: Mapped[str] = mapped_column(String(255), default="")
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    #: When consent was last given or added to, which is what the interface
    #: shows next to the application's name.
    approved_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class OAuthCode(Base):
    """One authorization code: hashed, single use, bound to a PKCE challenge."""

    __tablename__ = "oauth_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: SHA-256 of the code. The code itself is in a URL and therefore in
    #: somebody's browser history and possibly a proxy log; what is stored here
    #: is useless to whoever finds it there.
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    grant_id: Mapped[int] = mapped_column(
        ForeignKey("oauth_grants.id", ondelete="CASCADE"), index=True
    )
    #: Repeated from the request rather than joined to it, because the request
    #: row is spent the moment the code is issued and this has to outlive it.
    redirect_uri: Mapped[str] = mapped_column(String(500))
    scopes: Mapped[str] = mapped_column(String(255), default="")
    code_challenge: Mapped[str] = mapped_column(String(128), default="")
    nonce: Mapped[str] = mapped_column(String(255), default="")
    #: The rotation family every token issued from this code belongs to. Held
    #: here as well as on the tokens so that a code presented twice can burn
    #: what its first presentation produced.
    family: Mapped[str] = mapped_column(String(64), index=True, default="")
    #: When the person actually authenticated, for the ID token's ``auth_time``.
    authenticated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    #: Set when the code was exchanged. The row is kept rather than deleted, so
    #: that a second presentation is *detected* rather than merely refused --
    #: RFC 6749 §4.1.2 asks for the tokens from the first exchange to be revoked
    #: when that happens, and a deleted row cannot say which they were.
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires: Mapped[datetime] = mapped_column(DateTime, index=True)


class OAuthToken(Base):
    """An access or refresh token, hashed, in a rotation family."""

    __tablename__ = "oauth_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: ``access`` or ``refresh``.
    kind: Mapped[str] = mapped_column(String(8), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    grant_id: Mapped[int] = mapped_column(
        ForeignKey("oauth_grants.id", ondelete="CASCADE"), index=True
    )
    #: Every token descended from one authorization shares this. A refresh
    #: token presented after it was rotated away means somebody has a copy, and
    #: since there is no telling which of the two is the thief, the family goes.
    family: Mapped[str] = mapped_column(String(64), index=True)
    scopes: Mapped[str] = mapped_column(String(255), default="")
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires: Mapped[datetime] = mapped_column(DateTime, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class OAuthSigningKey(Base):
    """The RSA key ID tokens are signed with.

    More than one row can exist at a time, and that is rotation: the newest
    unretired key signs, and every key still in the table is published in the
    JWKS, so tokens signed before a rotation keep verifying until they expire.
    """

    __tablename__ = "oauth_signing_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: RFC 7638 thumbprint of the public half. Derived rather than assigned, so
    #: the same key names itself the same way in every copy of the database.
    kid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    #: PKCS#8 PEM. Secret, and the reason nothing serialises this table.
    private_pem: Mapped[str] = mapped_column(Text)
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    #: Set when a newer key took over. Still published, still verifying, no
    #: longer signing.
    retired_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
