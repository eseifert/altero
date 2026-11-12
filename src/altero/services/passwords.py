"""Password hashing and the policy applied before hashing.

Argon2id, through ``argon2-cffi``. Hand-rolling this is not the same kind of
exercise as hand-rolling TOTP: RFC 6238 publishes vectors that pin the answer,
whereas a password hash is only as good as its cost parameters, and getting
those wrong is silent. The library also knows when its own output was produced
at weaker settings, which is what :func:`needs_rehash` exposes.

The policy has a configurable floor, a ceiling and an offline common-password
blocklist. No composition rules or periodic resets are imposed, and accepted
passwords are never truncated or stripped before hashing.
"""

import gzip
from contextlib import suppress
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from argon2 import PasswordHasher
from argon2 import exceptions as argon2_exceptions
from argon2.profiles import RFC_9106_LOW_MEMORY

from altero.errors import InvalidInputError
from altero.settings import Settings, get_settings

#: Shortest password accepted. NIST SP 800-63B requires at least this for a
#: user-chosen secret; a second factor is available for anyone who wants more.
MINIMUM_LENGTH = 8

#: Longest password accepted. Argon2 is deliberately expensive to compute, so
#: an unbounded input is a way to spend the server's memory and CPU on demand.
#: Well above any real passphrase, and well under what would hurt.
MAXIMUM_LENGTH = 1024

#: RFC 9106's low-memory profile: 64 MiB and three passes. The high-memory
#: profile wants 2 GiB, which a container with a database beside it does not
#: have to spare on every login.
_hasher = PasswordHasher.from_parameters(RFC_9106_LOW_MEMORY)

#: Hashed once at import so that verifying against a user who does not exist,
#: or who has no password set, still costs a full Argon2 computation. Without
#: it, an unknown username answers measurably faster than a known one and the
#: login endpoint enumerates accounts.
#:
#: The plaintext is public -- it is on this line -- so a match against it must
#: never be reported as success. See :func:`verify_password`, which decides on
#: whether a credential existed rather than on whether the comparison passed.
_DUMMY_PASSWORD = "altero has no such user"
_DUMMY_HASH = _hasher.hash(_DUMMY_PASSWORD)


@dataclass(frozen=True, slots=True)
class PasswordPolicy:
    minimum_length: int = MINIMUM_LENGTH
    block_common: bool = True

    @classmethod
    def from_settings(cls, settings: Settings) -> PasswordPolicy:
        return cls(settings.password_min_length, settings.password_block_common)


@lru_cache(maxsize=1)
def _common_passwords() -> frozenset[str]:
    # Django 5.2's list, with its BSD license alongside. No network lookup.
    with gzip.open(
        Path(__file__).with_name("common-passwords.txt.gz"), "rt", encoding="utf-8"
    ) as source:
        return frozenset(word.strip().lower() for word in source)


def validate_password(password: str, *, policy: PasswordPolicy | None = None) -> None:
    """Raise :class:`InvalidInputError` unless ``password`` may be used.

    Blocklist comparison folds case/outer whitespace; hashing retains the secret.
    """
    policy = policy or PasswordPolicy.from_settings(get_settings())
    if len(password) < policy.minimum_length:
        raise InvalidInputError(f"A password must be at least {policy.minimum_length} characters")
    if len(password) > MAXIMUM_LENGTH:
        raise InvalidInputError(f"A password may be at most {MAXIMUM_LENGTH} characters")
    if policy.block_common and password.strip().lower() in _common_passwords():
        raise InvalidInputError(
            "That password is too common; choose a longer, less predictable phrase"
        )


def hash_password(
    password: str,
    *,
    memory_cost: int | None = None,
    time_cost: int | None = None,
) -> str:
    """Return an Argon2id hash of ``password``.

    The cost overrides exist so that a test can produce a deliberately weak
    hash and watch :func:`needs_rehash` notice. Nothing in the application
    passes them.
    """
    if memory_cost is None and time_cost is None:
        return _hasher.hash(password)

    weaker = PasswordHasher(
        memory_cost=memory_cost if memory_cost is not None else _hasher.memory_cost,
        time_cost=time_cost if time_cost is not None else _hasher.time_cost,
        parallelism=_hasher.parallelism,
    )
    return weaker.hash(password)


def verify_password(stored: str | None, password: str) -> bool:
    """Return whether ``password`` matches ``stored``.

    ``stored`` may be ``None`` for a user who has no password, or damaged by a
    bad restore. Both verify against the dummy hash instead of returning early:
    the answer is the same either way, and taking the same time to reach it is
    the point. Never raises -- a broken row must not turn every login attempt
    into a 500.
    """
    candidate = stored or _DUMMY_HASH
    try:
        _hasher.verify(candidate, password)
    except argon2_exceptions.VerificationError:
        return False
    except argon2_exceptions.InvalidHashError:
        # Not a hash we can read. Spend the work anyway, then refuse.
        with suppress(argon2_exceptions.VerificationError):
            _hasher.verify(_DUMMY_HASH, password)
        return False
    return stored is not None


def needs_rehash(stored: str) -> bool:
    """Return whether ``stored`` was produced at weaker parameters than current.

    Called after a successful verification, which is the only moment the plain
    password is in hand and an upgrade is possible. An unreadable hash reports
    ``False``: it cannot be upgraded, and saying otherwise would have the
    caller rewrite a row it does not understand.
    """
    try:
        return _hasher.check_needs_rehash(stored)
    except argon2_exceptions.InvalidHashError:
        return False
