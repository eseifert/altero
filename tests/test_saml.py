"""What a SAML service provider has to refuse.

Signed assertions are built here with a key of this file's own, so every check
can be exercised by changing one thing about an otherwise valid document.

The class that matters most is `TestSignatureWrapping`. `signxml` verifies the
signature and returns the *signed subtree*; altero reads claims out of that and
never out of the document it parsed. Wrapping a forged assertion around a
genuine signed one therefore yields a verified subtree that is still the
genuine one -- the forgery is not what gets read. That is structural rather
than a check, which is why it needs a test that would notice if the structure
were ever quietly changed.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree  # ty: ignore[unresolved-import]
from signxml import XMLSigner

from altero.errors import ForbiddenError
from altero.models import IdentityProvider
from altero.services import saml

ACS = "https://altero.example.org/web/auth/saml/campus/acs"
SP = "https://altero.example.org"
IDP = "https://sso.example.org/realms/campus"
REQUEST_ID = "_0123456789abcdef0123456789abcdef01234567"


def _keypair() -> tuple[rsa.RSAPrivateKey, str]:
    """A throwaway signing key and its certificate, in PEM."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-idp")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    pem = certificate.public_bytes(serialization.Encoding.PEM).decode()
    return key, pem


#: Built once: an RSA key pair is slow and none of these tests need a fresh one.
KEY, CERTIFICATE = _keypair()
OTHER_KEY, OTHER_CERTIFICATE = _keypair()


def provider(**overrides: Any) -> IdentityProvider:
    values: dict = {
        "slug": "campus",
        "kind": "saml",
        "idp_entity_id": IDP,
        "sso_url": f"{IDP}/protocol/saml",
        "certificates": CERTIFICATE,
        "username_claim": "username",
        "name_claim": "displayName",
        "email_claim": "email",
        "required_claim": "",
        "required_value": "",
    }
    values.update(overrides)
    return IdentityProvider(**values)


def _stamp(offset: timedelta = timedelta()) -> str:
    return (datetime.now(UTC) + offset).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def response_xml(
    *,
    status: str = saml.SUCCESS,
    issuer: str = IDP,
    audience: str | None = SP,
    recipient: str | None = ACS,
    in_response_to: str | None = REQUEST_ID,
    not_before: timedelta | None = timedelta(minutes=-1),
    not_on_or_after: timedelta | None = timedelta(minutes=5),
    assertion_id: str = "_assertion0000000000000000000000000000001",
    attributes: dict[str, list[str]] | None = None,
    name_id: str = "grace-subject-id",
) -> str:
    """Build a SAML Response with one assertion in it."""
    if attributes is None:
        attributes = {
            "username": ["grace"],
            "displayName": ["Grace Hopper"],
            "email": ["Grace@Example.org"],
        }

    statements = "".join(
        '<saml:Attribute Name="{name}" NameFormat='
        '"urn:oasis:names:tc:SAML:2.0:attrname-format:basic">{values}</saml:Attribute>'.format(
            name=name,
            values="".join(f"<saml:AttributeValue>{value}</saml:AttributeValue>" for value in vals),
        )
        for name, vals in attributes.items()
    )

    confirmation_attributes = []
    if recipient is not None:
        confirmation_attributes.append(f'Recipient="{recipient}"')
    if in_response_to is not None:
        confirmation_attributes.append(f'InResponseTo="{in_response_to}"')
    if not_on_or_after is not None:
        confirmation_attributes.append(f'NotOnOrAfter="{_stamp(not_on_or_after)}"')

    conditions_attributes = []
    if not_before is not None:
        conditions_attributes.append(f'NotBefore="{_stamp(not_before)}"')
    if not_on_or_after is not None:
        conditions_attributes.append(f'NotOnOrAfter="{_stamp(not_on_or_after)}"')

    audience_element = (
        f"<saml:AudienceRestriction><saml:Audience>{audience}</saml:Audience>"
        "</saml:AudienceRestriction>"
        if audience is not None
        else ""
    )

    return (
        '<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"'
        ' xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"'
        f' ID="_response000000000000000000000000000001" Version="2.0"'
        f' IssueInstant="{_stamp()}" InResponseTo="{in_response_to or ""}"'
        f' Destination="{ACS}">'
        f"<saml:Issuer>{issuer}</saml:Issuer>"
        f'<samlp:Status><samlp:StatusCode Value="{status}"/></samlp:Status>'
        f'<saml:Assertion ID="{assertion_id}" Version="2.0" IssueInstant="{_stamp()}">'
        f"<saml:Issuer>{issuer}</saml:Issuer>"
        "<saml:Subject>"
        f'<saml:NameID Format="urn:oasis:names:tc:SAML:2.0:nameid-format:persistent">'
        f"{name_id}</saml:NameID>"
        '<saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">'
        f"<saml:SubjectConfirmationData {' '.join(confirmation_attributes)}/>"
        "</saml:SubjectConfirmation>"
        "</saml:Subject>"
        f"<saml:Conditions {' '.join(conditions_attributes)}>{audience_element}</saml:Conditions>"
        f"<saml:AttributeStatement>{statements}</saml:AttributeStatement>"
        "</saml:Assertion>"
        "</samlp:Response>"
    )


def signed(xml: str | None = None, *, key: Any = None, **kwargs: Any) -> str:
    """Sign a response's assertion and return it base64-encoded, as the wire has it."""
    import base64

    document = etree.fromstring((xml or response_xml(**kwargs)).encode())
    assertion = document.find("./saml:Assertion", saml.NS)
    signer = XMLSigner(
        method=__import__("signxml").methods.enveloped,
        signature_algorithm="rsa-sha256",
        digest_algorithm="sha256",
        c14n_algorithm="http://www.w3.org/2001/10/xml-exc-c14n#",
    )
    using = key or KEY
    certificate = CERTIFICATE if using is KEY else OTHER_CERTIFICATE
    document.replace(assertion, signer.sign(assertion, key=using, cert=certificate))
    return base64.b64encode(etree.tostring(document)).decode()


def verify(encoded: str, **overrides: Any) -> saml.Verified:
    return saml.verify_response(
        encoded,
        provider(**overrides),
        acs_url=ACS,
        entity_id=SP,
        in_response_to=REQUEST_ID,
    )


class TestAGoodAssertion:
    async def test_it_is_accepted(self) -> None:
        result = verify(signed())

        assert result.assertion.subject == "grace-subject-id"
        assert result.assertion.username == "grace"

    async def test_the_attributes_are_read_out(self) -> None:
        result = verify(signed())

        assert result.assertion.display_name == "Grace Hopper"
        assert result.assertion.email == "grace@example.org"

    async def test_a_repeated_attribute_becomes_a_list(self) -> None:
        """Which is how group membership arrives, and what the required-claim
        check already handles for OIDC."""
        encoded = signed(attributes={"username": ["grace"], "groups": ["staff", "zotero"]})

        result = verify(encoded)

        assert result.assertion.claims["groups"] == ["staff", "zotero"]

    async def test_the_assertion_id_comes_back_for_the_replay_table(self) -> None:
        result = verify(signed())

        assert result.assertion_id == "_assertion0000000000000000000000000000001"


class TestTheSignature:
    async def test_an_unsigned_response_is_refused(self) -> None:
        import base64

        with pytest.raises(ForbiddenError):
            verify(base64.b64encode(response_xml().encode()).decode())

    async def test_a_signature_from_another_key_is_refused(self) -> None:
        with pytest.raises(ForbiddenError):
            verify(signed(key=OTHER_KEY))

    async def test_a_tampered_attribute_is_refused(self) -> None:
        """The whole point of signing it."""
        import base64

        encoded = signed()
        raw = base64.b64decode(encoded).replace(b"grace", b"root")

        with pytest.raises(ForbiddenError):
            verify(base64.b64encode(raw).decode())

    async def test_key_rollover_is_survivable(self) -> None:
        """A directory rolling its key publishes both for a while, and an
        instance that could hold one would go down in the middle of it."""
        both = f"{OTHER_CERTIFICATE}\n{CERTIFICATE}"

        result = verify(signed(), certificates=both)

        assert result.assertion.username == "grace"

    async def test_a_provider_with_no_certificate_is_refused(self) -> None:
        from altero.errors import InvalidInputError

        with pytest.raises(InvalidInputError):
            verify(signed(), certificates="")


class TestSignatureWrapping:
    """The attack this module's structure exists to defeat.

    A forged assertion is wrapped around a genuinely signed one. The signature
    still verifies -- it covers the genuine assertion, which is untouched --
    and a provider that then reads claims out of the *document* takes the
    forgery. altero reads them out of what `verify` returned instead.
    """

    async def test_a_forged_assertion_wrapped_around_a_signed_one_does_not_win(
        self,
    ) -> None:
        import base64

        genuine = etree.fromstring(base64.b64decode(signed()))
        forged = etree.fromstring(
            response_xml(
                # Its own id: reusing the signed one makes the reference
                # ambiguous and signxml refuses the document outright, which is
                # a different (and also correct) defence. This is the version
                # that gets past the signature check and has to be defeated by
                # reading only what was signed.
                assertion_id="_forgery000000000000000000000000000000001",
                name_id="root-subject-id",
                attributes={"username": ["root"]},
            ).encode()
        ).find("./saml:Assertion", saml.NS)
        # First in the document, so a naive `find` reaches the forgery before
        # the real one; the genuine signed assertion is left untouched.
        genuine.insert(0, forged)

        result = verify(base64.b64encode(etree.tostring(genuine)).decode())

        assert result.assertion.username == "grace"
        assert result.assertion.subject == "grace-subject-id"

    async def test_a_forgery_replacing_the_signed_one_is_refused(self) -> None:
        """Removing the signed assertion leaves nothing to verify."""
        import base64

        document = etree.fromstring(base64.b64decode(signed()))
        for assertion in document.findall("./saml:Assertion", saml.NS):
            document.remove(assertion)
        forged = etree.fromstring(
            response_xml(name_id="root", attributes={"username": ["root"]}).encode()
        ).find("./saml:Assertion", saml.NS)
        document.append(forged)

        with pytest.raises(ForbiddenError):
            verify(base64.b64encode(etree.tostring(document)).decode())


class TestTheChecksSignxmlDoesNotMake:
    async def test_a_failed_status_is_refused(self) -> None:
        with pytest.raises(ForbiddenError):
            verify(signed(status="urn:oasis:names:tc:SAML:2.0:status:Responder"))

    async def test_another_issuer_is_refused(self) -> None:
        with pytest.raises(ForbiddenError):
            verify(signed(issuer="https://sso.elsewhere.example"))

    async def test_an_assertion_for_another_service_is_refused(self) -> None:
        """The directory signed it perfectly well; it was simply not for us."""
        with pytest.raises(ForbiddenError):
            verify(signed(audience="https://someone-else.example.org"))

    async def test_an_expired_assertion_is_refused(self) -> None:
        with pytest.raises(ForbiddenError):
            verify(signed(not_before=timedelta(hours=-2), not_on_or_after=timedelta(hours=-1)))

    async def test_one_not_yet_valid_is_refused(self) -> None:
        with pytest.raises(ForbiddenError):
            verify(signed(not_before=timedelta(hours=1), not_on_or_after=timedelta(hours=2)))

    async def test_a_little_clock_skew_is_tolerated(self) -> None:
        """Refusing seconds of disagreement is an outage nobody can diagnose."""
        result = verify(
            signed(not_before=timedelta(minutes=1), not_on_or_after=timedelta(minutes=10))
        )

        assert result.assertion.username == "grace"

    async def test_an_assertion_posted_to_the_wrong_address_is_refused(self) -> None:
        with pytest.raises(ForbiddenError):
            verify(signed(recipient="https://altero.example.org/somewhere/else"))

    async def test_an_assertion_answering_another_request_is_refused(self) -> None:
        with pytest.raises(ForbiddenError):
            verify(signed(in_response_to="_some-other-request-entirely"))

    async def test_an_unsolicited_assertion_is_refused(self) -> None:
        """SP-initiated only: without a request to match, accepting one means
        accepting anything this directory's key ever signed."""
        with pytest.raises(ForbiddenError):
            verify(signed(in_response_to=None))


class TestReadingWhichRequestItAnswers:
    async def test_it_comes_out_of_the_response(self) -> None:
        assert saml.in_response_to(signed()) == REQUEST_ID

    async def test_an_unsolicited_one_has_none_and_is_refused(self) -> None:
        with pytest.raises(ForbiddenError):
            saml.in_response_to(signed(in_response_to=None))

    async def test_something_that_is_not_base64_is_refused(self) -> None:
        with pytest.raises(ForbiddenError):
            saml.in_response_to("@@@ not base64 @@@")

    async def test_something_that_is_not_xml_is_refused(self) -> None:
        import base64

        with pytest.raises(ForbiddenError):
            saml.in_response_to(base64.b64encode(b"not xml at all").decode())


class TestTheParserIsNotAWayIn:
    """A stranger's XML is parsed here, so the parser's configuration is a
    security property.

    `_parser` is private and tested directly anyway, because what it prevents
    cannot be observed through the public functions: a file read into an
    element nobody looks at leaks nothing *here* and everything the day
    somebody reads one. A test that went through `in_response_to` would pass
    with entity expansion switched fully on -- it did, until this was written.
    """

    async def test_an_external_entity_is_not_fetched(self, tmp_path: Path) -> None:
        """XXE: the classic way an XML endpoint reads the server's own files."""
        secret = tmp_path / "secret.txt"
        secret.write_text("TOPSECRETVALUE")
        document = (
            '<?xml version="1.0"?>'
            f'<!DOCTYPE r [<!ENTITY xxe SYSTEM "file://{secret}">]>'
            "<r>&xxe;</r>"
        )

        parsed = etree.fromstring(document.encode(), parser=saml._parser())

        assert "TOPSECRETVALUE" not in etree.tostring(parsed).decode()

    async def test_an_internal_entity_is_not_expanded(self) -> None:
        """The other half of the same setting, and where a billion laughs starts."""
        document = '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "AAAAAAAAAA">]><r>&a;</r>'

        parsed = etree.fromstring(document.encode(), parser=saml._parser())

        assert "AAAAAAAAAA" not in etree.tostring(parsed).decode()

    async def test_an_absurdly_large_document_is_refused_before_parsing(self) -> None:
        """A signature check on an unbounded document is unbounded work a
        stranger can ask for."""
        import base64

        huge = b"<r>" + b"a" * (saml.MAX_RESPONSE_BYTES + 1) + b"</r>"

        with pytest.raises(ForbiddenError):
            saml.in_response_to(base64.b64encode(huge).decode())


class TestTheAuthnRequest:
    async def test_it_goes_to_the_configured_endpoint(self) -> None:
        url = saml.authn_request_url(provider(), acs_url=ACS, entity_id=SP, request_id=REQUEST_ID)

        assert url.startswith(f"{IDP}/protocol/saml?")
        assert "SAMLRequest=" in url

    async def test_the_request_is_deflated_as_the_binding_requires(self) -> None:
        import base64
        import zlib
        from urllib.parse import parse_qs, urlparse

        url = saml.authn_request_url(provider(), acs_url=ACS, entity_id=SP, request_id=REQUEST_ID)

        packed = parse_qs(urlparse(url).query)["SAMLRequest"][0]
        document = zlib.decompress(base64.b64decode(packed), -zlib.MAX_WBITS).decode()
        assert f'ID="{REQUEST_ID}"' in document
        assert f"<saml:Issuer>{SP}</saml:Issuer>" in document
        assert f'AssertionConsumerServiceURL="{ACS}"' in document

    async def test_a_generated_id_is_one_xml_will_accept(self) -> None:
        """xsd:ID may not begin with a digit, and a hex token frequently does."""
        for _ in range(50):
            generated = saml.generate_request_id()
            assert not generated[0].isdigit()

    async def test_an_endpoint_that_already_has_a_query_keeps_it(self) -> None:
        with_query = provider(sso_url=f"{IDP}/protocol/saml?tenant=7")

        url = saml.authn_request_url(with_query, acs_url=ACS, entity_id=SP, request_id=REQUEST_ID)

        assert "tenant=7&SAMLRequest=" in url


class TestReadingCertificates:
    async def test_several_pem_blocks_are_separated(self) -> None:
        found = saml.certificates_of(provider(certificates=f"{CERTIFICATE}\n{OTHER_CERTIFICATE}"))

        assert len(found) == 2

    async def test_a_bare_body_is_given_its_armour(self) -> None:
        """Which is how SAML metadata carries one: <ds:X509Certificate> has no
        BEGIN or END line."""
        body = "".join(line for line in CERTIFICATE.splitlines() if "CERTIFICATE" not in line)

        found = saml.certificates_of(provider(certificates=body))

        assert len(found) == 1
        assert found[0].startswith("-----BEGIN CERTIFICATE-----")


class TestTheReplayGuard:
    """Nothing in SAML stops an assertion being presented twice. Noticing is
    the service provider's job, and the insert is how altero notices."""

    async def test_a_second_use_is_refused(self, session) -> None:  # type: ignore[no-untyped-def]
        from altero.services import samlreplay

        stored = provider()
        session.add(stored)
        await session.commit()
        expires = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)

        await samlreplay.consume(session, stored, assertion_id="_a1", expires=expires)

        with pytest.raises(ForbiddenError):
            await samlreplay.consume(session, stored, assertion_id="_a1", expires=expires)

    async def test_a_different_assertion_is_not(self, session) -> None:  # type: ignore[no-untyped-def]
        from altero.services import samlreplay

        stored = provider()
        session.add(stored)
        await session.commit()
        expires = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)

        await samlreplay.consume(session, stored, assertion_id="_a1", expires=expires)
        await samlreplay.consume(session, stored, assertion_id="_a2", expires=expires)

    async def test_one_past_its_expiry_stops_being_remembered(self, session) -> None:  # type: ignore[no-untyped-def]
        """Otherwise the table grows without bound on a busy instance."""
        from sqlalchemy import select

        from altero.models import ConsumedAssertion
        from altero.services import samlreplay

        stored = provider()
        session.add(stored)
        await session.commit()
        gone = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        await samlreplay.consume(session, stored, assertion_id="_old", expires=gone)

        await samlreplay.consume(
            session,
            stored,
            assertion_id="_new",
            expires=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
        )

        remaining = list(await session.scalars(select(ConsumedAssertion.assertion_id)))
        assert remaining == ["_new"]
