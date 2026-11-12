"""Eligibility policy for the future gated-registration workflow."""

import pytest

from altero.errors import ForbiddenError, InvalidInputError
from altero.services.registrationpolicy import RegistrationPolicy
from altero.settings import Settings


def policy(*domains: str, **settings: object) -> RegistrationPolicy:
    return RegistrationPolicy(
        Settings.model_validate(
            {
                "smtp_url": "smtp://relay.example.org",
                "public_url": "https://altero.example.org",
                **settings,
            }
        ),
        allowed_domains=domains,
    )


@pytest.mark.parametrize("settings", [{"smtp_url": ""}, {"public_url": ""}, {"sso_only": True}])
def test_gated_registration_requires_relay_origin_and_local_auth(
    settings: dict[str, object],
) -> None:
    with pytest.raises(ForbiddenError):
        policy(**settings)


@pytest.mark.parametrize(
    "origin",
    [
        "/relative",
        "//host.example",
        "ftp://host.example",
        "https://user:secret@host.example",
        "https://host.example/?x=y",
        "https://host.example/#fragment",
        "https://host.example:bad",
    ],
)
def test_the_origin_is_explicit_and_well_formed(origin: str) -> None:
    with pytest.raises(InvalidInputError):
        policy(public_url=origin)


def test_bad_relay_configuration_exposes_no_password() -> None:
    with pytest.raises(InvalidInputError) as caught:
        policy(smtp_url="invalid://user:secret@relay.example")
    assert "secret" not in str(caught.value)


def test_domains_are_normalized_deduplicated_and_matched_exactly() -> None:
    rules = policy(" EXAMPLE.ORG ", "example.org", "dept.example.org")
    assert rules.allowed_domains == ("example.org", "dept.example.org")
    assert rules.address(" ADA@EXAMPLE.ORG ") == "ada@example.org"
    assert rules.address("ada@dept.example.org") == "ada@dept.example.org"
    for address in ["ada@other.example.org", "ada@notexample.org", "ada@example.org.attacker.test"]:
        with pytest.raises(ForbiddenError):
            rules.address(address)


def test_an_empty_allowlist_accepts_any_valid_domain() -> None:
    assert policy().address("ada@elsewhere.example") == "ada@elsewhere.example"
    assert (
        policy("xn--bcher-kva.example").address("ada@xn--bcher-kva.example")
        == "ada@xn--bcher-kva.example"
    )


@pytest.mark.parametrize(
    "domain",
    [
        "*.example.org",
        ".example.org",
        "example.org.",
        "user@example.org",
        "example.org/path",
        "example..org",
        "-example.org",
        "example-.org",
        "exam_ple.org",
        "bücher.example",
        "",
        "x" * 64 + ".org",
        "x\x00.org",
    ],
)
def test_allowlist_entries_are_ascii_dns_names(domain: str) -> None:
    with pytest.raises(InvalidInputError):
        policy(domain)


@pytest.mark.parametrize(
    "address",
    [
        "invalid",
        "ada@*.example.org",
        "ada@example.org.",
        "ada@bücher.example",
        "ada\x00@example.org",
        "ada@example..org",
    ],
)
def test_invalid_addresses_are_refused_even_without_a_domain_restriction(address: str) -> None:
    with pytest.raises(InvalidInputError):
        policy().address(address)
