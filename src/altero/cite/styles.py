"""Finding the CSL style a request asks for.

Styles come from ``citeproc-py-styles``, a packaged copy of the Citation Style
Language repository, so an instance with no network still renders in any of the
several thousand published styles. That copy also carries the repository's own
``renamed-styles.json``, which is what lets a client keep asking for
``chicago-note-bibliography`` years after the CSL project renamed it -- the
alias is looked up rather than guessed.
"""

import json
from functools import lru_cache
from pathlib import Path

from altero.errors import InvalidInputError, NotFoundError

#: Style names are file names in the style repository. Anything else is a
#: malformed request rather than a style that happens to be missing; upstream
#: draws the same line, and it is also what keeps a name out of the filesystem.
_VALID_NAME = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."

#: The style the API renders in when the client names none, as upstream.
DEFAULT_STYLE = "chicago-note-bibliography"

#: The locale rendered in when the client names none.
DEFAULT_LOCALE = "en-US"


@lru_cache(maxsize=1)
def _renames() -> dict[str, str]:
    """Return the CSL repository's map of retired style names to current ones."""
    import citeproc_styles

    path = Path(citeproc_styles.__file__).parent / "styles" / "renamed-styles.json"
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as handle:
        renames: dict[str, str] = json.load(handle)
    return renames


@lru_cache(maxsize=256)
def style_path(name: str) -> str:
    """Return the file holding the named style.

    Raises:
        InvalidInputError: The name could not be a style name at all.
        NotFoundError: No style of that name is published.
    """
    from citeproc_styles import get_style_filepath
    from citeproc_styles.errors import StyleNotFoundError

    if not name or any(character not in _VALID_NAME for character in name):
        # A URL is a valid style to the reference implementation, whose citation
        # server fetches it. Fetching arbitrary URLs from here would make the
        # server a proxy for whoever holds an API key, so it is refused.
        raise InvalidInputError("Invalid style")

    for candidate in (name, _renames().get(name)):
        if candidate is None:
            continue
        try:
            return get_style_filepath(candidate)
        except StyleNotFoundError:
            continue

    raise NotFoundError("Style not found")
