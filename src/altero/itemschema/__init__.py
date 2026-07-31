"""The Zotero item type schema.

The schema in ``data/schema.json`` is vendored verbatim from
``https://api.zotero.org/schema``. It is the authority on which item types exist,
which fields and creator types each of them accepts, and how all of those are
named in 48 locales, so both the schema endpoints and write validation are driven
from it rather than from a hand-maintained copy.
"""

from altero.itemschema.registry import Schema, get_schema

__all__ = ["Schema", "get_schema"]
