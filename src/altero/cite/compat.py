"""A correction applied to citeproc-py before it renders anything.

citeproc-py does the CSL work here, and one of its behaviours differs from the
specification in a way that is plainly visible in ordinary output. A ``cs:group``
is suppressed when every variable it calls is empty, and the library excludes
``citation-number`` from what counts as a variable. A numeric style whose
citation is a group of that number and a locator macro -- IEEE is the popular
one -- therefore renders an empty citation, the locator being empty. CSL 1.0.1
counts ``citation-number`` as a number variable, and it is never empty for an
item that has been registered.

The correction is applied from the outside rather than by carrying a fork.
``tests/test_citations.py`` covers it against the style that shows it, so a
citeproc-py release that fixes this will surface as a test failure rather than
as silently duplicated work.
"""

from functools import lru_cache


@lru_cache(maxsize=1)
def apply() -> None:
    """Apply the correction once per process."""
    from citeproc.model import Text

    # `year-suffix` really is generated and may legitimately be empty;
    # `citation-number` is not.
    # The annotation citeproc-py infers for its own constant fixes the tuple's
    # length, so shortening it has to be spelled past the type checker.
    Text.generated_variables = ("year-suffix",)  # ty: ignore[invalid-assignment]
