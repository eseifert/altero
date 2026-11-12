"""Gated registration cannot start with log-delivered mail or a guessed origin."""

import pytest

from altero.app import create_app
from altero.errors import ForbiddenError, InvalidInputError
from altero.settings import Settings


@pytest.mark.parametrize("changes", [{"smtp_url": ""}, {"public_url": ""}, {"sso_only": True}])
def test_approval_prerequisites_are_enforced_at_startup(changes: dict[str, object]) -> None:
    settings = Settings.model_validate(
        {
            "registration_approval": True,
            "smtp_url": "smtp://localhost",
            "public_url": "https://trusted.example",
            **changes,
        }
    )
    with pytest.raises(ForbiddenError):
        create_app(settings)


def test_wildcard_domain_policy_cannot_start() -> None:
    with pytest.raises(InvalidInputError):
        create_app(
            Settings(
                registration_approval=True,
                smtp_url="smtp://localhost",
                public_url="https://trusted.example",
                registration_domains=["*.example.org"],
            )
        )
