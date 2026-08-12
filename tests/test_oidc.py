"""The OpenID Connect exchange, and what it refuses.

altero does not verify the ID token's signature: the token is fetched directly
from the token endpoint over TLS, which OpenID Connect Core §3.1.3.7 item 6
permits to be validated by the connection instead. That decision moves the
whole weight of the exchange onto the *claim* checks, so this file is mostly
about them. Each one is a way somebody else's token could otherwise sign its
holder in here.
"""

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest

from altero.errors import ForbiddenError
from altero.models import IdentityProvider
from altero.services import oidc

NONCE = "the-nonce-for-this-request"


def provider(**overrides: object) -> IdentityProvider:
    values: dict = {
        "slug": "campus",
        "kind": "oidc",
        "issuer": "https://sso.example.org",
        "client_id": "altero",
        "client_secret": "s3cret",
        "scopes": "profile email",
        "username_claim": "preferred_username",
        "name_claim": "name",
        "email_claim": "email",
        "required_claim": "",
        "required_value": "",
        "authorization_endpoint": "https://sso.example.org/authorize",
        "token_endpoint": "https://sso.example.org/token",
    }
    values.update(overrides)
    return IdentityProvider(**values)


def claims(**overrides: object) -> dict:
    now = datetime.now(UTC)
    base: dict = {
        "iss": "https://sso.example.org",
        "aud": "altero",
        "sub": "8f14e45f",
        "nonce": NONCE,
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "iat": int(now.timestamp()),
        "preferred_username": "ada",
        "name": "Ada Lovelace",
        "email": "Ada@Example.org",
    }
    base.update(overrides)
    return base


def token_for(payload: dict) -> str:
    """Build a JWT-shaped string. The signature is never read, so it is junk."""

    def segment(value: dict) -> str:
        raw = json.dumps(value).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{segment({'alg': 'RS256'})}.{segment(payload)}.not-a-signature"


class TestReadingTheToken:
    async def test_the_claims_come_back(self) -> None:
        assert oidc.read_id_token(token_for(claims()))["sub"] == "8f14e45f"

    async def test_something_that_is_not_a_token_is_refused(self) -> None:
        with pytest.raises(ForbiddenError):
            oidc.read_id_token("not a token")

    async def test_a_token_with_an_unreadable_payload_is_refused(self) -> None:
        with pytest.raises(ForbiddenError):
            oidc.read_id_token("header.@@@not-base64@@@.signature")

    async def test_the_header_is_never_read(self) -> None:
        """There is no `alg` for anybody to lie about, because none is looked at."""
        header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
        payload = token_for(claims()).split(".")[1]

        assert oidc.read_id_token(f"{header}.{payload}.")["sub"] == "8f14e45f"


class TestTheClaimChecks:
    def check(self, **overrides: object) -> None:
        oidc.validate_claims(claims(**overrides), provider(), nonce=NONCE)

    async def test_a_good_token_passes(self) -> None:
        self.check()

    async def test_a_token_from_another_issuer_is_refused(self) -> None:
        with pytest.raises(ForbiddenError):
            self.check(iss="https://sso.elsewhere.example")

    async def test_a_token_for_another_client_is_refused(self) -> None:
        """Otherwise any other client of the same directory signs its holder in."""
        with pytest.raises(ForbiddenError):
            self.check(aud="some-other-application")

    async def test_one_audience_among_several_is_enough(self) -> None:
        self.check(aud=["some-other-application", "altero"])

    async def test_an_authorized_party_naming_somebody_else_is_refused(self) -> None:
        with pytest.raises(ForbiddenError):
            self.check(aud=["altero", "other"], azp="other")

    async def test_the_wrong_nonce_is_refused(self) -> None:
        """Which is what stops a token from an earlier sign-in being replayed."""
        with pytest.raises(ForbiddenError):
            self.check(nonce="the-nonce-for-a-different-request")

    async def test_a_missing_nonce_is_refused(self) -> None:
        payload = claims()
        del payload["nonce"]
        with pytest.raises(ForbiddenError):
            oidc.validate_claims(payload, provider(), nonce=NONCE)

    async def test_an_expired_token_is_refused(self) -> None:
        past = datetime.now(UTC) - timedelta(hours=1)
        with pytest.raises(ForbiddenError):
            self.check(exp=int(past.timestamp()))

    async def test_a_little_clock_skew_is_tolerated(self) -> None:
        """Refusing seconds of disagreement would be an outage nobody can diagnose."""
        just_gone = datetime.now(UTC) - timedelta(minutes=1)
        self.check(exp=int(just_gone.timestamp()))

    async def test_a_token_dated_in_the_future_is_refused(self) -> None:
        ahead = datetime.now(UTC) + timedelta(hours=1)
        with pytest.raises(ForbiddenError):
            self.check(iat=int(ahead.timestamp()))

    async def test_a_token_with_no_expiry_is_refused(self) -> None:
        payload = claims()
        del payload["exp"]
        with pytest.raises(ForbiddenError):
            oidc.validate_claims(payload, provider(), nonce=NONCE)

    async def test_a_token_naming_nobody_is_refused(self) -> None:
        with pytest.raises(ForbiddenError):
            self.check(sub="")


class TestReadingSomebodyOut:
    async def test_the_configured_claims_are_used(self) -> None:
        assertion = oidc.assertion_from(claims(), provider())

        assert assertion.subject == "8f14e45f"
        assert assertion.username == "ada"
        assert assertion.display_name == "Ada Lovelace"

    async def test_the_address_is_folded(self) -> None:
        """It is stored lower-cased everywhere else, and compared that way."""
        assert oidc.assertion_from(claims(), provider()).email == "ada@example.org"

    async def test_a_directory_that_names_the_claim_differently_is_handled(self) -> None:
        """Azure sends `upn`; a server that could not say so would make
        accounts called a1b2c3d4-...."""
        payload = claims(upn="ada@example.org")

        assertion = oidc.assertion_from(payload, provider(username_claim="upn"))

        assert assertion.username == "ada@example.org"

    async def test_a_missing_username_claim_falls_back_to_the_subject(self) -> None:
        payload = claims()
        del payload["preferred_username"]

        assert oidc.assertion_from(payload, provider()).username == "8f14e45f"

    async def test_a_claim_of_an_odd_shape_does_not_raise(self) -> None:
        """A directory sending a list where a string was expected must not 500."""
        payload = claims(name=["Ada", "Lovelace"])

        assert oidc.assertion_from(payload, provider()).display_name == "ada"


class TestTheRequiredClaim:
    async def test_a_provider_naming_none_requires_nothing(self) -> None:
        assert oidc.satisfies_requirement({}, provider())

    async def test_the_named_value_is_accepted(self) -> None:
        entitled = provider(required_claim="groups", required_value="zotero")

        assert oidc.satisfies_requirement({"groups": "zotero"}, entitled)

    async def test_a_list_carrying_it_is_accepted(self) -> None:
        """Directories send one group as a string and several as a list."""
        entitled = provider(required_claim="groups", required_value="zotero")

        assert oidc.satisfies_requirement({"groups": ["staff", "zotero"]}, entitled)

    async def test_a_list_without_it_is_refused(self) -> None:
        entitled = provider(required_claim="groups", required_value="zotero")

        assert not oidc.satisfies_requirement({"groups": ["staff"]}, entitled)

    async def test_the_claim_being_absent_is_refused(self) -> None:
        entitled = provider(required_claim="groups", required_value="zotero")

        assert not oidc.satisfies_requirement({"sub": "x"}, entitled)

    async def test_a_claim_with_no_value_named_only_has_to_be_there(self) -> None:
        entitled = provider(required_claim="entitlement")

        assert oidc.satisfies_requirement({"entitlement": "anything"}, entitled)
        assert not oidc.satisfies_requirement({"entitlement": ""}, entitled)


class TestPkce:
    async def test_the_challenge_is_the_sha256_of_the_verifier(self) -> None:
        """S256 and never plain: a plain challenge *is* the verifier, so
        whoever can read the authorization request can complete the exchange."""
        import hashlib

        verifier = oidc.generate_verifier()
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )

        assert oidc.challenge_for(verifier) == expected

    async def test_a_verifier_is_within_the_length_the_rfc_allows(self) -> None:
        for _ in range(20):
            assert 43 <= len(oidc.generate_verifier()) <= 128

    async def test_two_verifiers_differ(self) -> None:
        assert oidc.generate_verifier() != oidc.generate_verifier()


class TestTheAuthorizationUrl:
    def parsed(self, prompt: str | None = None) -> dict[str, str]:
        from urllib.parse import parse_qs, urlparse

        url = oidc.authorization_url(
            provider(),
            redirect_uri="https://altero.example.org/web/auth/sso/campus/callback",
            state="the-state",
            nonce=NONCE,
            verifier="a" * 64,
            prompt=prompt,
        )
        return {name: value[0] for name, value in parse_qs(urlparse(url).query).items()}

    async def test_it_asks_for_a_code_and_carries_pkce(self) -> None:
        parameters = self.parsed()

        assert parameters["response_type"] == "code"
        assert parameters["code_challenge_method"] == "S256"
        assert parameters["code_challenge"] == oidc.challenge_for("a" * 64)

    async def test_openid_is_always_in_the_scope(self) -> None:
        assert "openid" in self.parsed()["scope"].split()

    async def test_the_scope_has_no_duplicates(self) -> None:
        url = oidc.authorization_url(
            provider(scopes="openid profile"),
            redirect_uri="https://x/callback",
            state="s",
            nonce="n",
            verifier="a" * 64,
        )
        from urllib.parse import parse_qs, urlparse

        scope = parse_qs(urlparse(url).query)["scope"][0].split()
        assert scope.count("openid") == 1

    async def test_re_authentication_asks_the_directory_to_ask_again(self) -> None:
        """Otherwise a session the directory still holds answers for presence."""
        assert self.parsed(prompt="login")["prompt"] == "login"

    async def test_an_ordinary_sign_in_sends_no_prompt(self) -> None:
        assert "prompt" not in self.parsed()


class TestDiscoveryFreshness:
    async def test_a_provider_with_no_endpoints_needs_it(self) -> None:
        assert oidc.needs_discovery(provider(authorization_endpoint="", token_endpoint=""))

    async def test_a_provider_that_has_never_run_it_needs_it(self) -> None:
        assert oidc.needs_discovery(provider(discovered=None))

    async def test_a_recent_one_does_not(self) -> None:
        recent = provider(discovered=datetime.now(UTC).replace(tzinfo=None))

        assert not oidc.needs_discovery(recent)

    async def test_a_stale_one_is_fetched_again(self) -> None:
        """So a directory that moves an endpoint is followed without anybody
        having to notice and re-save the configuration."""
        stale = datetime.now(UTC).replace(tzinfo=None) - oidc.DISCOVERY_MAX_AGE - timedelta(hours=1)

        assert oidc.needs_discovery(provider(discovered=stale))
