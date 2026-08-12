"""The little XML writer the RDF, MODS, TEI and EndNote formats share.

:mod:`xml.etree.ElementTree` would do this, but not the part that matters here:
these documents are read by people as often as by programs, so the indentation
and the order of everything is part of the output, and ElementTree's namespace
handling rewrites the prefixes the translators chose -- `bib:Article` is what a
Zotero RDF file has said since 2006 and what every importer greps for.

The one thing this deliberately does not reproduce is upstream's *whitespace*.
Zotero's RDF serialiser indents an element with one child differently from one
with two, and writes a line of three spaces into an empty document; those are
artefacts of the library it is built on rather than decisions, and no RDF or XML
parser can tell the difference. Everything a parser can see is reproduced.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from xml.sax.saxutils import escape, quoteattr

INDENT = "    "


@dataclass(frozen=True, slots=True)
class Element:
    """One element: a name, attributes in order, and text or children."""

    name: str
    attributes: tuple[tuple[str, str], ...] = ()
    text: str | None = None
    children: tuple[Element, ...] = ()

    def render(self, depth: int = 0) -> str:
        """Return this element and everything under it, indented from ``depth``."""
        pad = INDENT * depth
        attributes = "".join(
            f" {name}={quoteattr(value)}" for name, value in self.attributes if value is not None
        )
        if self.children:
            inside = "".join(child.render(depth + 1) for child in self.children)
            return f"{pad}<{self.name}{attributes}>\n{inside}{pad}</{self.name}>\n"
        if not self.text:
            return f"{pad}<{self.name}{attributes}/>\n"
        return f"{pad}<{self.name}{attributes}>{escape(self.text)}</{self.name}>\n"

    def compact(self) -> str:
        """Return this element on one line, with no whitespace of its own.

        EndNote's XML is serialised by a DOM and so carries no indentation at
        all; the reader it is written for is a program, and a newline the
        document did not have is a newline in somebody's abstract.
        """
        attributes = "".join(
            f" {name}={quoteattr(value)}" for name, value in self.attributes if value is not None
        )
        if self.children:
            inside = "".join(child.compact() for child in self.children)
            return f"<{self.name}{attributes}>{inside}</{self.name}>"
        if not self.text:
            return f"<{self.name}{attributes}/>"
        return f"<{self.name}{attributes}>{escape(self.text)}</{self.name}>"


@dataclass
class Builder:
    """An element's children, gathered one at a time.

    The translators are written as a run of `if (item.x) add(...)` statements
    and the order they run in is the order the file comes out in, so this keeps
    that shape rather than building a dict and sorting it.
    """

    children: list[Element] = field(default_factory=list)

    def add(self, name: str, value: str, *attributes: tuple[str, str]) -> None:
        """Add an element carrying text, or nothing at all when it is empty."""
        if value:
            self.children.append(Element(name, tuple(attributes), text=value))

    def add_element(self, element: Element | None) -> None:
        if element is not None:
            self.children.append(element)

    def extend(self, elements: Iterable[Element]) -> None:
        self.children.extend(elements)

    def build(self, name: str, *attributes: tuple[str, str]) -> Element:
        return Element(name, tuple(attributes), children=tuple(self.children))


def document(root: Element) -> str:
    """Return a complete document, declaration included."""
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + root.render()


def namespaces(entries: Sequence[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    """Return namespace declarations as attributes of the root element."""
    return tuple((f"xmlns:{prefix}" if prefix else "xmlns", uri) for prefix, uri in entries)
