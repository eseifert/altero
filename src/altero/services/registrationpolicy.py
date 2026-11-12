"""Eligibility rules for opt-in verified registration and address changes."""

import re
from dataclasses import InitVar, dataclass
from urllib.parse import urlsplit

from altero.errors import ForbiddenError, InvalidInputError
from altero.services import emailverify
from altero.services.mail import SmtpConfig
from altero.settings import Settings

_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", re.ASCII)


def configured(settings: Settings) -> RegistrationPolicy | None:
    return (
        RegistrationPolicy(settings, allowed_domains=tuple(settings.registration_domains))
        if settings.registration_approval
        else None
    )


def _domain(value: str) -> str:
    domain = value.strip().lower()
    if len(domain) > 253 or not all(_LABEL.fullmatch(label) for label in domain.split(".")):
        raise InvalidInputError("Registration domains must be ASCII DNS names without wildcards")
    return domain


@dataclass(frozen=True, slots=True)
class RegistrationPolicy:
    """Validate configured prerequisites and exact mailbox domains.

    Empty domains allow any valid DNS domain. Subdomains must be listed
    explicitly; internationalized names use their ASCII (punycode) spelling.
    Settings are checked at construction and are not retained, including relay
    credentials. This proves neither relay reachability nor institutional status.
    """

    settings: InitVar[Settings]
    allowed_domains: tuple[str, ...] = ()

    def __post_init__(self, settings: Settings) -> None:
        if settings.sso_only:
            raise ForbiddenError("Gated registration is unavailable in SSO-only mode")
        if not settings.smtp_url or not settings.public_url:
            raise ForbiddenError(
                "Gated registration requires ALTERO_SMTP_URL and ALTERO_PUBLIC_URL"
            )
        try:
            SmtpConfig.from_url(settings.smtp_url)
        except ValueError:
            raise InvalidInputError("Gated registration requires a valid SMTP relay URL") from None
        try:
            origin = urlsplit(settings.public_url)
            valid = (
                origin.scheme in {"http", "https"}
                and origin.hostname
                and not origin.username
                and not origin.password
                and not origin.query
                and not origin.fragment
            )
            _ = origin.port
        except ValueError:
            valid = False
        if not valid:
            raise InvalidInputError("Gated registration requires an absolute HTTP(S) public URL")
        object.__setattr__(
            self, "allowed_domains", tuple(dict.fromkeys(_domain(d) for d in self.allowed_domains))
        )

    def address(self, email: str) -> str:
        """Normalize a candidate address and enforce the current domain ceiling."""
        address = emailverify.normalise(email)
        if "\x00" in address:
            raise InvalidInputError("Registration fields may not contain null characters")
        domain = address.rsplit("@", 1)[1]
        if _domain(domain) != domain:
            raise InvalidInputError("That does not look like a registration domain")
        if self.allowed_domains and domain not in self.allowed_domains:
            raise ForbiddenError("That email domain is not eligible for registration")
        return address
