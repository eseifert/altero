"""Signing in against somebody else's directory.

Three tables, and the split between them is the point.

:class:`IdentityProvider` is the operator's configuration: which directory,
reached how, and what it is allowed to do to accounts here. It is a database
row rather than a setting in ``config.py`` because it is a nested object with a
secret in it, and :mod:`altero.services.instancesettings` is deliberately a
store of bounded integers.

:class:`FederatedIdentity` is one account's link to one subject in one
directory. The subject is the identity; an email claim is not, which is why
nothing here matches on one -- see :mod:`altero.services.oidc`.

:class:`AuthRequest` is a sign-in part-way through happening. It is in the
database rather than in memory because ``services/streaming.py`` and
``services/migrations.py`` are already documented as working in one process and
no further, and signing in is not something that may break behind two workers.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func, true
from sqlalchemy.orm import Mapped, mapped_column

from altero.db import Base


class IdentityProvider(Base):
    """A directory this instance will accept a sign-in from."""

    __tablename__ = "identity_providers"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: Appears in URLs -- ``/web/auth/sso/<slug>/start`` -- so it is short,
    #: stable and chosen by the operator rather than generated.
    slug: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    #: ``oidc`` or ``saml``. One table for both because everything except the
    #: protocol columns is shared, and an operator's screen listing "the ways
    #: in to this instance" should not be two lists.
    kind: Mapped[str] = mapped_column(String(8), default="oidc")
    #: What the button on the sign-in page says.
    display_name: Mapped[str] = mapped_column(String(64), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

    # --- OIDC ---------------------------------------------------------------
    #: The issuer, which is also where discovery hangs off.
    issuer: Mapped[str] = mapped_column(String(255), default="")
    client_id: Mapped[str] = mapped_column(String(255), default="")
    #: Stored as given and never returned by the API. The admin screen is told
    #: whether one is set and may replace it, the way a key is shown once and
    #: as four characters afterwards.
    client_secret: Mapped[str] = mapped_column(Text, default="")
    #: Extra scopes beyond ``openid``, space separated.
    scopes: Mapped[str] = mapped_column(String(255), default="profile email")

    #: Discovery, cached. Refetched when :attr:`discovered` is older than
    #: :data:`altero.services.oidc.DISCOVERY_MAX_AGE`, so an endpoint that
    #: moves is picked up without an operator having to notice.
    authorization_endpoint: Mapped[str] = mapped_column(String(500), default="")
    token_endpoint: Mapped[str] = mapped_column(String(500), default="")
    userinfo_endpoint: Mapped[str] = mapped_column(String(500), default="")
    discovered: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    # --- What a claim means here --------------------------------------------
    #: Which claim carries the username, the display name and the address. Each
    #: configurable because directories disagree: ``preferred_username`` is the
    #: OIDC standard and Azure sends ``upn``, and an instance that could not say
    #: so would make accounts called ``a1b2c3d4-....``.
    username_claim: Mapped[str] = mapped_column(String(64), default="preferred_username")
    name_claim: Mapped[str] = mapped_column(String(64), default="name")
    email_claim: Mapped[str] = mapped_column(String(64), default="email")

    #: Whether a subject nobody here has linked may have an account made for
    #: it. Off by default: an instance that turns this on has decided that
    #: everybody in the directory may have a library here, which is a policy
    #: rather than a detail.
    create_accounts: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- Lifecycle ----------------------------------------------------------
    #: A claim that must be present, and the value it must carry, for a
    #: sign-in through this provider to be allowed. Empty means no such check.
    #: This is the deprovisioning half: when somebody leaves the group the
    #: claim names, the next sign-in suspends the account rather than
    #: succeeding. See :mod:`altero.services.federation`.
    required_claim: Mapped[str] = mapped_column(String(64), default="")
    required_value: Mapped[str] = mapped_column(String(255), default="")
    #: Whether losing the claim also drops every API key. Off by default:
    #: suspension already refuses both credentials, and keeping the keys is
    #: what makes reinstating somebody restore their sync rather than make
    #: them set every client up again.
    revoke_keys_on_loss: Mapped[bool] = mapped_column(Boolean, default=False)

    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FederatedIdentity(Base):
    """One account's link to one subject in one directory.

    The subject is what identifies somebody, and nothing else is. An email
    claim looks like it would do -- it is human-readable and already on the
    account -- and using it would mean any directory that can assert an address
    could take the account holding it, which is the classic way federated
    sign-in is broken into. Linking an existing account is therefore something
    the account does while signed in, not something a first sign-in guesses at.
    """

    __tablename__ = "federated_identities"
    __table_args__ = (UniqueConstraint("provider_id", "subject", name="uq_identity_subject"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("identity_providers.id", ondelete="CASCADE"), index=True
    )
    #: The ``sub`` claim. Opaque, stable for the life of the account at the
    #: provider, and the only thing here that decides who somebody is.
    subject: Mapped[str] = mapped_column(String(255))
    #: What the directory last called them, kept so the administration screen
    #: can show a link as something other than a UUID.
    asserted_name: Mapped[str] = mapped_column(String(255), default="")
    linked: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class AuthRequest(Base):
    """A federated sign-in between leaving here and coming back.

    Holds what the callback has to check and cannot be told by the caller: the
    state it must match, the PKCE verifier, the nonce that pins the token to
    this request, and where to go afterwards. Rows are single use and short
    lived.
    """

    __tablename__ = "auth_requests"

    #: The ``state`` parameter, and the primary key: one lookup, and a state
    #: that does not resolve is a request that was never made here.
    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("identity_providers.id", ondelete="CASCADE"), index=True
    )
    #: PKCE. Sent only on the back channel, so an authorization code
    #: intercepted in the browser cannot be exchanged by whoever took it.
    code_verifier: Mapped[str] = mapped_column(String(128), default="")
    #: Echoed in the ID token, which is what stops a token minted for another
    #: request being replayed into this one.
    nonce: Mapped[str] = mapped_column(String(64), default="")
    #: Where in the interface to return to, so following a deep link and being
    #: sent to sign in does not land somewhere else afterwards.
    next_path: Mapped[str] = mapped_column(String(500), default="")
    #: Set when this trip is to prove an already signed-in browser again, or to
    #: attach a new identity to it, rather than to sign somebody in.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), default=None
    )
    #: ``login``, ``link`` or ``reauth`` -- what the callback should do with a
    #: successful assertion. Carried here rather than guessed at from whether a
    #: session exists, because a signed-in browser starting a plain sign-in is
    #: a real case.
    purpose: Mapped[str] = mapped_column(String(8), default="login")
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires: Mapped[datetime] = mapped_column(DateTime, index=True)
