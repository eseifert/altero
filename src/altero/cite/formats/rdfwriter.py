"""The RDF/XML the Zotero and Bibliontology formats are written with.

Both translators build a graph and hand it to Zotero's RDF serialiser, which
writes a resource as an element named after its type, its literals as child
elements, and a blank node inside whichever statement points at it. That is
what this reproduces: a :class:`Node` is one resource, and rendering one writes
everything below it.

Two differences from upstream, both of them invisible to an RDF parser. The
namespaces are all declared on the root element rather than only the ones an
item turned out to use -- a file is written in batches here and the root goes
out before the first item does. And the indentation is even, where Zotero's
serialiser indents a resource with one child by three spaces and one with two by
four.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from xml.sax.saxutils import escape, quoteattr

RDF_NAMESPACE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"

INDENT = "    "


@dataclass
class Node:
    """One resource: what it is, what identifies it, and what is said about it."""

    #: The element the resource is written as, such as `bib:Article`. A
    #: resource with no type of its own is an `rdf:Description`.
    type_name: str | None = None
    #: What identifies it. A resource with none is a blank node and is written
    #: inside the statement that points at it.
    about: str | None = None
    #: A label for a node with no address that is spoken of in more than one
    #: place -- a person who is both the creator and an entry in the author
    #: list. Assigned by :func:`label_shared_nodes` rather than by hand.
    node_id: str | None = None
    #: `(predicate, literal or node)` in the order they were said.
    statements: list[tuple[str, str | Node]] = field(default_factory=list)

    def add(self, predicate: str, value: str) -> None:
        """Say something about this resource, or nothing when the value is empty."""
        if value:
            self.statements.append((predicate, value))

    def add_node(self, predicate: str, node: Node) -> None:
        self.statements.append((predicate, node))

    def render(self, depth: int = 1, *, named: Sequence[str] = ()) -> str:
        """Return this resource and everything below it.

        Args:
            named: Addresses written as resources of their own elsewhere in the
                document, so a statement reaching one points at it rather than
                repeating it.
        """
        pad = INDENT * depth
        name = self.type_name or "rdf:Description"
        if self.about:
            attributes = f" rdf:about={quoteattr(self.about)}"
        elif self.node_id:
            attributes = f" rdf:nodeID={quoteattr(self.node_id)}"
        else:
            attributes = ""

        if not self.statements:
            return f"{pad}<{name}{attributes}/>\n"

        inside = []
        for predicate, value in self.statements:
            if isinstance(value, str):
                inside.append(f"{pad}{INDENT}<{predicate}>{escape(value)}</{predicate}>\n")
            elif value.about and value.about in named:
                inside.append(
                    f"{pad}{INDENT}<{predicate} rdf:resource={quoteattr(value.about)}/>\n"
                )
            elif value.node_id:
                inside.append(
                    f"{pad}{INDENT}<{predicate} rdf:nodeID={quoteattr(value.node_id)}/>\n"
                )
            else:
                inside.append(
                    f"{pad}{INDENT}<{predicate}>\n"
                    f"{value.render(depth + 2, named=named)}"
                    f"{pad}{INDENT}</{predicate}>\n"
                )
        return f"{pad}<{name}{attributes}>\n{''.join(inside)}{pad}</{name}>\n"


def label_shared_nodes(roots: Sequence[Node]) -> list[Node]:
    """Label every blank node spoken of more than once, and return them.

    A node written inside the one statement that mentions it needs no name. One
    mentioned twice -- a creator is both the work's creator and an entry in its
    author list -- has to be written once and pointed at, which in RDF/XML means
    a node id.
    """
    counts: dict[int, int] = {}
    nodes: dict[int, Node] = {}
    walked: set[int] = set()

    def walk(node: Node) -> None:
        # Once per node rather than once per mention, or a resource reached
        # from two roots would have its own children counted twice.
        if id(node) in walked:
            return
        walked.add(id(node))
        for _, value in node.statements:
            if isinstance(value, str):
                continue
            counts[id(value)] = counts.get(id(value), 0) + 1
            nodes[id(value)] = value
            walk(value)

    for root in roots:
        walk(root)

    shared = []
    for index, (key, count) in enumerate(counts.items(), start=1):
        node = nodes[key]
        if count > 1 and not node.about:
            node.node_id = f"n{index}"
            shared.append(node)
    return shared


def document_start(namespaces: Sequence[tuple[str, str]]) -> str:
    """Return the opening `<rdf:RDF>` with its namespace declarations."""
    declarations = "".join(f'\n xmlns:{prefix}="{uri}"' for prefix, uri in namespaces)
    return f"<rdf:RDF{declarations}>\n"


DOCUMENT_END = "</rdf:RDF>\n"
