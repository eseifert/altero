"""Citation rendering: CSL JSON, bibliographies and citations.

Kept out of the API layer like every other core module -- these functions take
items and plain values and know nothing about requests.
"""

from altero.cite.csljson import csl_item, csl_items
from altero.cite.dates import csl_date
from altero.cite.export import bibtex, ris
from altero.cite.render import bibliography, citation
from altero.cite.styles import DEFAULT_LOCALE, DEFAULT_STYLE, style_path

__all__ = [
    "DEFAULT_LOCALE",
    "DEFAULT_STYLE",
    "bibliography",
    "bibtex",
    "citation",
    "csl_date",
    "csl_item",
    "csl_items",
    "ris",
    "style_path",
]
