"""Notes as clients have written them, for the desktop's note editor to save again.

The `note-corpus` acceptance scenario stores each of these in a desktop, has the
shipped note editor write it back, and records both. The web interface's own
editor is then held to the same output (`web/src/notes/corpus.spec.ts`).

Left out on purpose: images given as `data:` URLs, which the desktop's editor
imports as attachments the moment a note is opened, so its output would say
what the import did rather than what the editor writes.
"""

import json
from urllib.parse import quote


def _encoded(value) -> str:
    return quote(json.dumps(value, separators=(",", ":")), safe="")


ITEM_URI = "http://zotero.org/users/1/items/CITED234"
ATTACHMENT_URI = "http://zotero.org/users/1/items/PDFFILE2"

CITATION_ITEMS = _encoded(
    [
        {
            "uris": [ITEM_URI],
            "itemData": {
                "id": ITEM_URI,
                "type": "book",
                "title": "On the Economy of Machinery and Manufactures",
                "author": [{"family": "Babbage", "given": "Charles"}],
                "issued": {"date-parts": [["1832"]]},
            },
        }
    ]
)
CITATION = _encoded({"citationItems": [{"uris": [ITEM_URI], "locator": "12"}], "properties": {}})
TWO_CITATIONS = _encoded(
    {
        "citationItems": [
            {"uris": [ITEM_URI], "prefix": "see"},
            {"uris": [ITEM_URI], "locator": "3-5"},
        ],
        "properties": {},
    }
)
ANNOTATION = _encoded(
    {
        "attachmentURI": ATTACHMENT_URI,
        "annotationKey": "ANNOT234",
        "color": "#ffd400",
        "pageLabel": "4",
        "position": {"pageIndex": 3, "rects": [[10, 20, 30, 40]]},
        "citationItem": {"uris": [ITEM_URI], "locator": "4"},
    }
)
OLD_ANNOTATION = _encoded({"uri": ATTACHMENT_URI, "text": "old", "position": {"pageIndex": 0}})
V1_CITATION = _encoded(
    {
        "citationItems": [
            {
                "uris": [ITEM_URI],
                "itemData": {
                    "type": "book",
                    "title": "Embedded",
                    "author": [{"family": "Babbage"}],
                },
            }
        ],
        "properties": {},
    }
)


def wrapped(body: str, version: int = 9, items: bool = False) -> str:
    attributes = f'data-citation-items="{CITATION_ITEMS}" ' if items else ""
    return f'<div {attributes}data-schema-version="{version}">{body}</div>'


CASES: list[tuple[str, str]] = [
    ("plain paragraph", "<p>The engine weaves algebraic patterns.</p>"),
    ("plain text without markup", "Typed into an old client"),
    (
        "current editor output",
        wrapped("<h1>Title</h1>\n<p>Some <strong>bold</strong> and <em>italic</em>.</p>\n"),
    ),
    ("headings one to six", "".join(f"<h{n}>Heading {n}</h{n}>" for n in range(1, 7))),
    (
        "nested lists",
        '<ul><li>one</li><li>two<ul><li>nested</li></ul></li></ul><ol start="3"><li>'
        "<p>three</p><p>four</p></li></ol>",
    ),
    (
        "table with spans and colour",
        "<table><tbody><tr><th>head</th>"
        '<td colspan="2" style="background-color: #ffd400">cell</td></tr>'
        '<tr><td rowspan="2">a</td></tr></tbody></table>',
    ),
    (
        "table without tbody, ragged",
        "<table><tr><td>one</td><td>two</td></tr><tr><td>three</td></tr></table>",
    ),
    (
        "TinyMCE indent, alignment and direction",
        '<p style="padding-left: 40px;">one</p>'
        '<p style="padding-left: 80px; text-align: center;">two</p>'
        '<p dir="rtl" style="padding-right: 40px">שלום</p><p style="text-align: justify">just</p>',
    ),
    (
        "TinyMCE formatting tags",
        "<p><b>b</b> <i>i</i> <u>u</u> <strike>s</strike> <sub>2</sub> <sup>3</sup> "
        '<font color="#ff0000" face="Arial">font</font> <span style="text-decoration: '
        'underline;">su</span></p>',
    ),
    (
        "colours: hex, names, functions, highlight",
        '<p><span style="color: #ff2020">red</span> <span style="color: blue">blue</span> '
        '<span style="color: rgb(0, 128, 0)">green</span> <span style="background-color: '
        '#ffd40080">hi</span> '
        '<span style="background-color: #FFD400">HI</span> <span style="background: '
        'yellow">bg</span></p>',
    ),
    (
        "links and code",
        '<p><a href="https://example.org/a?b=1&amp;c=2" title="T">link</a> '
        '<a href="mailto:a@example.org">mail</a> '
        "<code>x  y</code> <kbd>k</kbd></p>",
    ),
    ("code block with runs of spaces", "<pre>def f():\n    return  1\n\n</pre>"),
    (
        "maths",
        '<pre class="math">$$x^2 + y^2$$</pre><p>inline <span class="math">$a  b$</span> maths</p>',
    ),
    (
        "quote and rule",
        "<blockquote><p>quoted</p><blockquote>nested</blockquote></blockquote><hr><p>after</p>",
    ),
    ("line breaks", "<p>one<br>two<br></p><h2>head<br>line</h2>"),
    (
        "Google Docs paste",
        '<p><b style="font-weight:normal" id="docs-internal-guid-1">'
        '<span style="font-weight: 700">bold</span> '
        '<span style="font-style: italic">it</span> <span style="font-family: '
        'monospace">mono</span></b></p>',
    ),
    (
        "sequential and non-breaking spaces",
        "<p>a\u00a0 b   c\u00a0\u00a0d</p><p>\u00a0\u00a0\u00a0lead</p>",
    ),
    ("decomposed accents", "<p>e\u0301te\u0301 A\u030a</p>"),
    (
        "entities and quotes",
        "<p>&lt;tag&gt; &amp; &quot;q&quot; \u2018single\u2019 «guill» „low“</p>",
    ),
    (
        "citations with item data",
        wrapped(
            f'<p>As shown <span class="citation" data-citation="{CITATION}">(stale)</span> and '
            f'<span class="citation" data-citation="{TWO_CITATIONS}">(x)</span>.</p>\n',
            items=True,
        ),
    ),
    (
        "highlight annotation",
        wrapped(
            f'<p><span class="highlight" data-annotation="{ANNOTATION}">“quoted”</span> '
            f'<span class="citation" data-citation="{CITATION}">(x)</span></p>\n',
            items=True,
        ),
    ),
    (
        "underline annotation, schema 10",
        wrapped(
            f'<p><span class="underline" data-annotation="{ANNOTATION}">under</span></p>\n',
            10,
            True,
        ),
    ),
    (
        "annotation in its pre-v4 form",
        f'<p><span class="highlight" data-annotation="{OLD_ANNOTATION}">old</span></p>',
    ),
    (
        "embedded image attachment",
        '<p><img data-attachment-key="IMAGEKY2" width="200" height="100" '
        f'data-annotation="{ANNOTATION}"></p>',
    ),
    ("remote image", '<p><img src="https://example.org/a.png" alt="A" title="T" width="50"></p>'),
    (
        "schema version 1",
        wrapped(f'<p><span class="citation" data-citation="{V1_CITATION}">(x)</span></p>', 1),
    ),
    (
        "unknown elements",
        "<div><div>nested</div><span>span</span></div><center>c</center><dl><dt>t</dt>"
        "<dd>d</dd></dl>",
    ),
    ("right-to-left list", '<ul dir="rtl"><li>א</li><li>ב</li></ul>'),
]
