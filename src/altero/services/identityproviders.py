"""The directories an operator has told this instance to accept.

Configuration that lives in the database rather than in ``config.py``, and the
reason is the shape of it: a provider is a nested object with a secret in it,
and :mod:`altero.services.instancesettings` is deliberately a store of bounded
integers -- its ``Definition`` describes a retention period, not this.

The secret is stored as given and is never returned. The administration screen
is told whether one is set and may replace it, the way an API key is shown once
and as four characters afterwards: a signed-in browser tab must not be a way of
reading back a credential the instance holds for somebody else's directory.
"""

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import InvalidInputError, NotFoundError
from altero.models import IdentityProvider

#: Appears in a URL, so the same rule the rest of altero uses for a path
#: segment: letters, digits and a hyphen.
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")

KINDS = ("oidc", "saml")

#: Everything an administrator may set. Named rather than taken from the model
#: so that adding a column does not silently make it writable from the browser.
WRITABLE = (
    "display_name",
    "enabled",
    "issuer",
    "client_id",
    "client_secret",
    "scopes",
    "username_claim",
    "name_claim",
    "email_claim",
    "create_accounts",
    "required_claim",
    "required_value",
    "revoke_keys_on_loss",
)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def validate_slug(slug: str) -> str:
    candidate = slug.strip().lower()
    if not _SLUG.match(candidate):
        raise InvalidInputError(
            "A provider's name may hold lower-case letters, digits and hyphens, "
            "and is what appears in the sign-in address"
        )
    return candidate


def serialise(provider: IdentityProvider) -> dict[str, Any]:
    """Render a provider for the administration screen, without its secret."""
    return {
        "id": provider.id,
        "slug": provider.slug,
        "kind": provider.kind,
        "displayName": provider.display_name,
        "enabled": provider.enabled,
        "issuer": provider.issuer,
        "clientId": provider.client_id,
        # Whether there is one, never what it is.
        "hasClientSecret": bool(provider.client_secret),
        "scopes": provider.scopes,
        "usernameClaim": provider.username_claim,
        "nameClaim": provider.name_claim,
        "emailClaim": provider.email_claim,
        "createAccounts": provider.create_accounts,
        "requiredClaim": provider.required_claim,
        "requiredValue": provider.required_value,
        "revokeKeysOnLoss": provider.revoke_keys_on_loss,
        "discovered": provider.discovered.isoformat() + "Z" if provider.discovered else None,
        "authorizationEndpoint": provider.authorization_endpoint,
        "tokenEndpoint": provider.token_endpoint,
    }


def public(provider: IdentityProvider) -> dict[str, str]:
    """Render a provider for the sign-in page.

    Three fields and no more. This is served to anybody who loads the page, so
    it says what the button should read and where it goes, and nothing about
    how the instance is configured.
    """
    return {
        "slug": provider.slug,
        "kind": provider.kind,
        "displayName": provider.display_name or provider.slug,
    }


async def list_all(session: AsyncSession) -> list[IdentityProvider]:
    result = await session.scalars(select(IdentityProvider).order_by(IdentityProvider.slug))
    return list(result)


async def list_enabled(session: AsyncSession) -> list[IdentityProvider]:
    """Return the providers a sign-in page should offer.

    A provider missing the endpoints it needs is left out rather than drawn as
    a button that fails: discovery has not run, or it failed, and either way
    there is nothing behind it yet.
    """
    result = await session.scalars(
        select(IdentityProvider)
        .where(IdentityProvider.enabled.is_(True))
        .order_by(IdentityProvider.slug)
    )
    return [entry for entry in result if entry.authorization_endpoint]


async def by_slug(session: AsyncSession, slug: str) -> IdentityProvider:
    provider = await session.scalar(
        select(IdentityProvider).where(IdentityProvider.slug == slug.strip().lower())
    )
    if provider is None:
        raise NotFoundError("No such identity provider")
    return provider


async def create(session: AsyncSession, *, slug: str, kind: str, **values: Any) -> IdentityProvider:
    """Add a provider. Discovery is a separate step, and may fail without
    losing what was typed."""
    name = validate_slug(slug)
    if kind not in KINDS:
        raise InvalidInputError(f"A provider is one of {', '.join(KINDS)}")

    taken = await session.scalar(select(IdentityProvider).where(IdentityProvider.slug == name))
    if taken is not None:
        raise InvalidInputError(f"There is already a provider called '{name}'")

    provider = IdentityProvider(slug=name, kind=kind)
    _apply(provider, values)
    session.add(provider)
    await session.commit()
    return provider


async def update(
    session: AsyncSession, provider: IdentityProvider, values: dict[str, Any]
) -> IdentityProvider:
    """Change a provider.

    An absent ``client_secret`` leaves the stored one alone, which is what lets
    the screen save every other field without being able to read the secret
    back first. An explicitly empty one clears it.
    """
    _apply(provider, values)
    await session.commit()
    return provider


def _apply(provider: IdentityProvider, values: dict[str, Any]) -> None:
    for name in WRITABLE:
        if name not in values:
            continue
        value = values[name]
        if name == "issuer" and value:
            value = str(value).strip().rstrip("/")
            if not value.startswith(("http://", "https://")):
                raise InvalidInputError("An issuer is an absolute https URL")
            # Discovery has to run again: the endpoints cached below belong to
            # whatever issuer they were fetched from.
            if value != provider.issuer:
                provider.discovered = None
        setattr(provider, name, value)


async def record_discovery(
    session: AsyncSession,
    provider: IdentityProvider,
    *,
    authorization_endpoint: str,
    token_endpoint: str,
    userinfo_endpoint: str,
) -> None:
    """Store what a provider published, so a sign-in need not fetch it again."""
    provider.authorization_endpoint = authorization_endpoint
    provider.token_endpoint = token_endpoint
    provider.userinfo_endpoint = userinfo_endpoint
    provider.discovered = _now()
    await session.commit()


async def delete(session: AsyncSession, provider: IdentityProvider) -> None:
    """Remove a provider, and with it every account's link to it.

    The accounts stay. Somebody whose only way in was this provider is left
    unable to sign in, which is the operator's decision to make and is why the
    screen says how many links will go before it asks again.
    """
    await session.delete(provider)
    await session.commit()
