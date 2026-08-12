"""A SAML 2.0 service provider, for directories that speak nothing else.

`signxml` verifies the XML signature and altero does not attempt to. That is
not modesty: XML canonicalisation is where naive implementations grow
signature-wrapping holes, and the defence against those is structural rather
than a check you can add. :meth:`signxml.XMLVerifier.verify` returns the
*signed subtree*, and **every claim read below comes out of that return value
and never out of the document that was parsed**. An attacker who wraps a
forged assertion around a genuine signed one therefore gets a verified
subtree that is still the genuine one; the forgery is simply not what is read.
That rule is the single most important line in this module.

What `signxml` does not do, and what the rest of this module is:

- ``Status`` being ``Success`` before anything else is looked at.
- ``Conditions/@NotBefore`` and ``@NotOnOrAfter``, with a clock skew.
- ``AudienceRestriction`` naming this service provider and not another.
- ``SubjectConfirmationData/@Recipient`` equal to the address the assertion
  actually arrived at, and ``@InResponseTo`` equal to the request altero sent.
- Replay: an assertion id is remembered until it could no longer be used --
  see :class:`~altero.models.ConsumedAssertion`. Nothing in the specification
  stops an assertion being presented twice; noticing is the provider's job.

**SP-initiated only.** An unsolicited assertion has no ``InResponseTo`` to
check, so accepting one means accepting anything the directory's key ever
signed, for any service, at any time. Refusing them costs an
identity-provider-initiated "launch from the portal" button and buys the whole
class of attack that replaying a captured assertion represents. altero refuses
them.

Not implemented, and each deliberately: encrypted assertions (TLS already
covers the transport, and a decryption key would be another thing to hold),
Single Logout (it is unreliable in practice and altero's session is its own),
and the artifact binding.
"""

import base64
import logging
import secrets
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

# lxml ships partial stubs and ty cannot see `etree` through them; signxml's
# own test extra pulls lxml-stubs for the same reason. The alternative is a
# dev dependency for one import.
from lxml import etree  # ty: ignore[unresolved-import]
from signxml import XMLVerifier

from altero.errors import ForbiddenError, InvalidInputError
from altero.models import IdentityProvider
from altero.services.oidc import Assertion

logger = logging.getLogger("altero.saml")

NS = {
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
}

SUCCESS = "urn:oasis:names:tc:SAML:2.0:status:Success"
BEARER = "urn:oasis:names:tc:SAML:2.0:cm:bearer"

#: Clock skew allowed on every time bound in an assertion. Directories and
#: servers disagree by seconds, and refusing a sign-in for that is an outage
#: nobody can diagnose from this side.
CLOCK_SKEW = timedelta(minutes=5)

#: How long an assertion id is remembered when the assertion names no expiry of
#: its own. Long enough to cover any window it could plausibly be replayed in.
DEFAULT_REPLAY_MEMORY = timedelta(hours=12)

#: The largest response this will parse. A signature check on an unbounded
#: document is a way of being asked to do unbounded work by a stranger.
MAX_RESPONSE_BYTES = 512 * 1024


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def generate_request_id() -> str:
    """Return an id an XML ``ID`` attribute will accept.

    ``xsd:ID`` may not begin with a digit, and a hex token frequently does --
    which is why this is not just ``token_hex``.
    """
    return f"_{secrets.token_hex(20)}"


def _parser() -> etree.XMLParser:
    """Return a parser that will not fetch or expand anything.

    Every one of these is a way an XML document from a stranger becomes a
    request to somewhere else, a local file read, or an exhausted server.
    """
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
    )


def certificates_of(provider: IdentityProvider) -> list[str]:
    """Return the provider's signing certificates, one per entry.

    Several because a directory rolling its key over publishes both for a
    while, and an instance that could hold only one would go down in the
    middle of that.
    """
    found: list[str] = []
    current: list[str] = []
    for line in provider.certificates.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        current.append(stripped)
        if "END CERTIFICATE" in stripped:
            found.append("\n".join(current))
            current = []
    if current:
        # A bare base64 body with no armour, which is how SAML metadata carries
        # one -- <ds:X509Certificate> has no BEGIN/END lines.
        body = "".join(current)
        found.append(f"-----BEGIN CERTIFICATE-----\n{body}\n-----END CERTIFICATE-----")
    return found


def authn_request_url(
    provider: IdentityProvider,
    *,
    acs_url: str,
    entity_id: str,
    request_id: str,
    relay_state: str = "",
) -> str:
    """Return where to send the browser, over the HTTP-Redirect binding.

    Deflated and base64-encoded as the binding requires. The request is not
    signed: altero has no signing key, and an unsigned AuthnRequest is what the
    binding permits and what directories accept by default. Nothing in it is a
    secret, and the *response* is what has to be signed.
    """
    issued = _now().replace(microsecond=0).isoformat() + "Z"
    document = (
        '<samlp:AuthnRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"'
        ' xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"'
        f' ID="{request_id}" Version="2.0" IssueInstant="{issued}"'
        f' Destination="{_escape(provider.sso_url)}"'
        ' ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"'
        f' AssertionConsumerServiceURL="{_escape(acs_url)}">'
        f"<saml:Issuer>{_escape(entity_id)}</saml:Issuer>"
        '<samlp:NameIDPolicy AllowCreate="true"'
        ' Format="urn:oasis:names:tc:SAML:2.0:nameid-format:persistent"/>'
        "</samlp:AuthnRequest>"
    )

    # Raw DEFLATE, without the zlib header the binding does not want.
    compressor = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
    packed = compressor.compress(document.encode()) + compressor.flush()

    parameters = {"SAMLRequest": base64.b64encode(packed).decode()}
    if relay_state:
        parameters["RelayState"] = relay_state

    separator = "&" if "?" in provider.sso_url else "?"
    return f"{provider.sso_url}{separator}{urlencode(parameters)}"


def _escape(value: str) -> str:
    """Escape a value going into an attribute or element text."""
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _instant(value: str | None) -> datetime | None:
    """Parse a SAML timestamp, which is always UTC and may carry a Z."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def in_response_to(encoded: str) -> str:
    """Return which request a response claims to answer, before verifying it.

    Read from the *unverified* document, and that is safe for exactly one use:
    choosing which :class:`~altero.models.AuthRequest` row to look up. It
    proves nothing on its own, and :func:`verify_response` checks the same
    value again inside the signature, against the ``SubjectConfirmationData``
    that the directory actually signed. A forged value therefore selects a row
    that will not match, or no row at all.

    It is needed at all because the row is what says which sign-in this
    answers, and the row has to be found before there is anything to check
    against.
    """
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as broken:
        raise ForbiddenError("That sign-in could not be read") from broken

    if len(raw) > MAX_RESPONSE_BYTES:
        raise ForbiddenError("That sign-in could not be read")

    try:
        document = etree.fromstring(raw, parser=_parser())
    except etree.XMLSyntaxError as broken:
        raise ForbiddenError("That sign-in could not be read") from broken

    answering = document.get("InResponseTo")
    if not answering:
        # An unsolicited assertion. Refused here rather than later, because
        # there is no request row it could ever match -- see this module's
        # docstring on why altero is SP-initiated only.
        raise ForbiddenError("That sign-in does not answer a request from here")
    return answering


@dataclass(frozen=True, slots=True)
class Verified:
    """A checked assertion, and what has to be remembered about it."""

    assertion: Assertion
    #: The assertion's own id, for the replay table.
    assertion_id: str
    #: How long that id is worth remembering.
    expires: datetime


def verify_response(
    encoded: str,
    provider: IdentityProvider,
    *,
    acs_url: str,
    entity_id: str,
    in_response_to: str,
    now: datetime | None = None,
) -> Verified:
    """Check a SAML response and return who it says signed in.

    Raises :class:`~altero.errors.ForbiddenError` for anything wrong. The
    message is deliberately the same shape throughout: whoever is submitting a
    forged assertion should not be told which check caught it, and whoever is
    submitting a genuine one cannot act on the difference either.
    """
    moment = now or _now()

    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as broken:
        raise ForbiddenError("That sign-in could not be read") from broken

    if len(raw) > MAX_RESPONSE_BYTES:
        raise ForbiddenError("That sign-in could not be read")

    certificates = certificates_of(provider)
    if not certificates:
        raise InvalidInputError("This provider has no signing certificate configured")

    try:
        document = etree.fromstring(raw, parser=_parser())
    except etree.XMLSyntaxError as broken:
        raise ForbiddenError("That sign-in could not be read") from broken

    # Read before verification, because a failed sign-in has to be reported
    # rather than merely refused -- and because a response whose status is not
    # Success carries no assertion to verify in the first place.
    status = document.find("./samlp:Status/samlp:StatusCode", NS)
    if status is None or status.get("Value") != SUCCESS:
        raise ForbiddenError("The identity provider refused that sign-in")

    signed = _verified_subtree(raw, certificates)

    # From here on, `signed` and nothing else. Reading a claim out of
    # `document` would be the signature-wrapping hole this module exists to
    # avoid -- see the module docstring.
    assertion = _assertion_in(signed)
    _check_issuer(assertion, provider)
    _check_conditions(assertion, entity_id=entity_id, moment=moment)
    confirmed_until = _check_subject(
        assertion, acs_url=acs_url, in_response_to=in_response_to, moment=moment
    )

    assertion_id = assertion.get("ID") or ""
    if not assertion_id:
        raise ForbiddenError("That sign-in could not be read")

    return Verified(
        assertion=_read_out(assertion, provider),
        assertion_id=assertion_id,
        expires=confirmed_until or moment + DEFAULT_REPLAY_MEMORY,
    )


def _verified_subtree(raw: bytes, certificates: list[str]) -> Any:
    """Return the signed subtree, trying each configured certificate.

    Several because of key rollover. The last failure is what is logged; what
    the caller is told is that the sign-in was refused, since "which of our
    certificates did not match" is not the submitter's business.
    """
    last: Exception | None = None
    for certificate in certificates:
        try:
            result = XMLVerifier().verify(raw, x509_cert=certificate)
        except Exception as failure:  # signxml raises a family of its own
            last = failure
            continue
        # signxml returns a list when a document carries several signatures --
        # a directory that signs both the response and the assertion. The
        # assertion is the one worth reading.
        found: list[Any] = list(result) if isinstance(result, list) else [result]
        subtrees = [one.signed_xml for one in found]
        for subtree in subtrees:
            if _holds_assertion(subtree):
                return subtree
        if subtrees:
            return subtrees[0]
    logger.warning("No configured certificate verified the assertion: %s", last)
    raise ForbiddenError("That sign-in could not be verified")


def _holds_assertion(signed: Any) -> bool:
    """Return whether this signed subtree is, or contains, an Assertion."""
    return (
        signed.tag == f"{{{NS['saml']}}}Assertion"
        or signed.find("./saml:Assertion", NS) is not None
    )


def _assertion_in(signed: Any) -> Any:
    """Return the Assertion element within what was signed.

    A directory may sign the response, the assertion, or both. Either is
    acceptable; what is not acceptable is reading an assertion that was not
    inside whatever the signature covered, which is why this looks only at
    ``signed``.
    """
    tag = f"{{{NS['saml']}}}Assertion"
    if signed.tag == tag:
        return signed
    found = signed.find("./saml:Assertion", NS)
    if found is None:
        raise ForbiddenError("That sign-in carried nothing that was signed")
    return found


def _check_issuer(assertion: Any, provider: IdentityProvider) -> None:
    issuer = assertion.findtext("./saml:Issuer", namespaces=NS)
    if (issuer or "").strip() != provider.idp_entity_id:
        raise ForbiddenError("That sign-in came from a different identity provider")


def _check_conditions(assertion: Any, *, entity_id: str, moment: datetime) -> None:
    """Check the window it is valid in, and who it was minted for."""
    conditions = assertion.find("./saml:Conditions", NS)
    if conditions is None:
        raise ForbiddenError("That sign-in carries no conditions")

    not_before = _instant(conditions.get("NotBefore"))
    if not_before is not None and moment + CLOCK_SKEW < not_before:
        raise ForbiddenError("That sign-in is not valid yet")

    not_after = _instant(conditions.get("NotOnOrAfter"))
    if not_after is not None and moment - CLOCK_SKEW >= not_after:
        raise ForbiddenError("That sign-in has expired")

    # An assertion minted for another service provider must not be usable here,
    # which is the whole point of the restriction and is not checked by
    # verifying the signature -- the directory signed it perfectly well.
    restrictions = conditions.findall("./saml:AudienceRestriction", NS)
    if restrictions:
        audiences = {
            (text or "").strip()
            for restriction in restrictions
            for text in (element.text for element in restriction.findall("./saml:Audience", NS))
        }
        if entity_id not in audiences:
            raise ForbiddenError("That sign-in was not issued for this server")


def _check_subject(
    assertion: Any, *, acs_url: str, in_response_to: str, moment: datetime
) -> datetime | None:
    """Check the bearer confirmation, and return when it stops being usable.

    ``InResponseTo`` is what makes this SP-initiated only: an unsolicited
    assertion has none, and accepting one means accepting anything this
    directory's key ever signed.
    """
    subject = assertion.find("./saml:Subject", NS)
    if subject is None:
        raise ForbiddenError("That sign-in names nobody")

    for confirmation in subject.findall("./saml:SubjectConfirmation", NS):
        if confirmation.get("Method") != BEARER:
            continue
        data = confirmation.find("./saml:SubjectConfirmationData", NS)
        if data is None:
            continue

        recipient = (data.get("Recipient") or "").strip()
        if recipient and recipient.rstrip("/") != acs_url.rstrip("/"):
            continue

        if data.get("InResponseTo") != in_response_to:
            continue

        not_after = _instant(data.get("NotOnOrAfter"))
        if not_after is not None and moment - CLOCK_SKEW >= not_after:
            continue

        return not_after

    raise ForbiddenError("That sign-in does not answer this request")


def _read_out(assertion: Any, provider: IdentityProvider) -> Assertion:
    """Turn a verified assertion into the same shape OIDC produces.

    One :class:`~altero.services.oidc.Assertion` for both protocols, so
    ``services/federation.py`` has one path and cannot come to treat a SAML
    sign-in differently from an OIDC one by accident.
    """
    attributes: dict[str, Any] = {}
    for attribute in assertion.findall("./saml:AttributeStatement/saml:Attribute", NS):
        name = attribute.get("Name") or ""
        values = [
            (element.text or "").strip()
            for element in attribute.findall("./saml:AttributeValue", NS)
        ]
        if not name:
            continue
        # One value stays a string and several become a list, which is how a
        # group membership claim arrives and what `satisfies_requirement`
        # already handles for OIDC.
        attributes[name] = values[0] if len(values) == 1 else values
        friendly = attribute.get("FriendlyName")
        if friendly and friendly not in attributes:
            attributes[friendly] = attributes[name]

    name_id = (assertion.findtext("./saml:Subject/saml:NameID", namespaces=NS) or "").strip()
    subject = str(attributes.get("subject") or name_id)
    if not subject:
        raise ForbiddenError("That sign-in names nobody")

    def text(claim: str) -> str:
        value = attributes.get(claim)
        if isinstance(value, str):
            return value
        if isinstance(value, list) and value:
            return str(value[0])
        return ""

    username = text(provider.username_claim) or name_id
    return Assertion(
        subject=subject,
        username=username,
        display_name=text(provider.name_claim) or username,
        email=text(provider.email_claim).lower(),
        claims={"sub": subject, **attributes},
    )
