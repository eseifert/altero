"""What an OAuth scope is allowed to mean.

The one rule this module exists to enforce: **a scope grants exactly what it
says and nothing else.** A consent screen that names three permissions and hands
over five is worse than no consent screen at all, because the person read it and
believed it.

The scopes that reach a library map one-for-one onto the flags an API key
already carries. That is deliberate and it is what makes the mapping provable:
a token cannot express access an API key could not, so
:func:`altero.services.auth.access_for` needs no new concept, and the four
ceilings it already applies to a key -- the key's grants, group membership, the
group's policy, the member's own permission -- apply unchanged to a token.

``openid``, ``profile`` and ``email`` are identity scopes. They reach no
library, no item and no file. A token holding nothing else can call
``/oauth/userinfo`` and nothing more.
"""

from dataclasses import dataclass

from altero.errors import InvalidInputError

#: Identity. Required for an OpenID Connect request, and on its own it is the
#: whole of what such a request gets: who you are, and no library at all.
OPENID = "openid"
PROFILE = "profile"
EMAIL = "email"

LIBRARY_READ = "library.read"
LIBRARY_WRITE = "library.write"
NOTES_READ = "notes.read"
FILES_READ = "files.read"
GROUPS_READ = "groups.read"
GROUPS_WRITE = "groups.write"

#: Every scope this server issues, in the order the consent screen lists them.
ALL = (
    OPENID,
    PROFILE,
    EMAIL,
    LIBRARY_READ,
    LIBRARY_WRITE,
    NOTES_READ,
    FILES_READ,
    GROUPS_READ,
    GROUPS_WRITE,
)

#: Scopes whose absence makes another scope useless. Write access implies read
#: access in :func:`~altero.services.auth.access_for` -- a key that may write
#: but not read can do neither -- so a request for ``library.write`` alone
#: would be granted and then do nothing. Refused at the door instead, because a
#: token that silently does nothing is a bug report nobody can reproduce.
REQUIRES = {
    LIBRARY_WRITE: LIBRARY_READ,
    GROUPS_WRITE: GROUPS_READ,
    NOTES_READ: LIBRARY_READ,
    FILES_READ: LIBRARY_READ,
}


@dataclass(frozen=True, slots=True)
class Capabilities:
    """What a set of scopes grants, in the vocabulary an API key already uses."""

    library_read: bool = False
    library_write: bool = False
    notes_read: bool = False
    files_read: bool = False
    all_groups_read: bool = False
    all_groups_write: bool = False


def parse(raw: str) -> list[str]:
    """Return the scopes in ``raw``, deduplicated, in the canonical order.

    A scope string is space separated per RFC 6749 §3.3. Order is normalised so
    that the same request always produces the same stored string, which is what
    lets a standing grant be compared against a new request by set membership
    without worrying about how the application wrote it.
    """
    present = set(raw.split())
    return [scope for scope in ALL if scope in present]


def validate(raw: str) -> list[str]:
    """Return the scopes in ``raw``, or refuse to.

    Refusing rather than dropping the unknown ones: an application asking for
    ``annotations.write`` has a belief about what this server does, and quietly
    issuing a token without it produces an application that half works and a
    person who cannot tell which half.
    """
    requested = raw.split()
    if not requested:
        raise InvalidInputError("No scope requested")

    unknown = [scope for scope in requested if scope not in ALL]
    if unknown:
        raise InvalidInputError(
            f"Unknown scope {' '.join(sorted(unknown))}. This server issues: {' '.join(ALL)}"
        )

    granted = set(requested)
    for scope, prerequisite in REQUIRES.items():
        if scope in granted and prerequisite not in granted:
            raise InvalidInputError(f"{scope} is useless without {prerequisite}; ask for both")

    return parse(raw)


def capabilities(scopes: str) -> Capabilities:
    """Return what ``scopes`` grants.

    Written out one line per scope rather than computed, so that reading this
    function is the same as reading the table of what a token can do. The
    identity scopes appear nowhere in it, which is the point.
    """
    granted = set(scopes.split())
    return Capabilities(
        library_read=LIBRARY_READ in granted,
        library_write=LIBRARY_WRITE in granted,
        notes_read=NOTES_READ in granted,
        files_read=FILES_READ in granted,
        all_groups_read=GROUPS_READ in granted,
        all_groups_write=GROUPS_WRITE in granted,
    )


def covers(granted: str, requested: str) -> bool:
    """Return whether a standing grant already covers a fresh request.

    What decides whether the consent screen has anything to ask. Set
    containment, so an application asking for less than last time is not asked
    again, and one asking for anything new is.
    """
    return set(requested.split()) <= set(granted.split())


def union(granted: str, requested: str) -> str:
    """Return the scopes a grant holds after ``requested`` is approved on top."""
    return " ".join(parse(f"{granted} {requested}"))
