"""PDF inspection for duplicate merging, outside the server process.

``hash_text`` ports ``hashAttachmentText``/``getMostCommonWords`` from Zotero
10.0.6's ``mergeItems.mjs``. Markup types are ``hasAnyAnnotations`` from its
document-worker submodule, pin 8fb70af, ``src/pdf/annotations/read.js``.

pypdf supplies text and annotation dictionaries instead of the desktop's PDF
worker. A parse error, encryption, resource limit or timeout means "possibly
annotated", just as the desktop's ``logAndBeSafe`` path does. No original PDF
is modified. Keep parsing isolated: a thread timeout would leave a malformed
document consuming server resources after its request had ended.
"""

import asyncio
import hashlib
import json
import logging
import sys
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path

# PyICU exports these from its C++ extension without Python typing metadata.
from icu import Collator, Locale  # ty: ignore[unresolved-import]
from pypdf import PdfReader

logger = logging.getLogger(__name__)
WORKER_TIMEOUT = 30
MAX_TEXT_FILE_SIZE = 500_000_000

# ECMAScript \s, which differs from Python's str.isspace() (notably U+0085).
_WHITESPACE = frozenset(
    "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006"
    "\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
)
_MARKUP = frozenset(
    {
        "/Text",
        "/FreeText",
        "/Line",
        "/Square",
        "/Circle",
        "/Polygon",
        "/PolyLine",
        "/Highlight",
        "/Underline",
        "/Squiggly",
        "/StrikeOut",
        "/Stamp",
        "/Caret",
        "/Ink",
        "/FileAttachment",
        "/Sound",
        "/Redact",
    }
)


@dataclass(frozen=True, slots=True)
class PDFInfo:
    text_hash: str | None = None
    has_annotations: bool = True


def hash_text(text: str, locale: str = "en-US") -> str | None:
    """Fingerprint the 50 most frequent words, requiring ten unique words.

    Only Unicode letters survive, with length > 3 in JavaScript's UTF-16 code
    units. Punctuation and digits are removed, not treated as separators.
    Tied frequencies use the desktop's base-strength ICU collation; the final
    hash sorts the selected words by JavaScript's default UTF-16 order.
    """
    counts: dict[str, int] = {}
    word: list[str] = []

    def finish() -> None:
        value = "".join(word)
        if len(value.encode("utf-16-be")) > 6:
            counts[value] = counts.get(value, 0) + 1
        word.clear()

    for char in text:
        if char in _WHITESPACE:
            finish()
        elif char.isalpha():
            word.append(char.lower())
    finish()
    if len(counts) < 10:
        return None
    collator = Collator.createInstance(Locale.forLanguageTag(locale))
    collator.setStrength(Collator.PRIMARY)
    words = sorted(counts, key=lambda value: (-counts[value], collator.getSortKey(value)))[:50]
    words.sort(key=lambda value: value.encode("utf-16-be"))
    return hashlib.md5(" ".join(words).encode(), usedforsecurity=False).hexdigest()


def _inspect(path: Path, locale: str, *, text: bool) -> PDFInfo:
    with path.open("rb") as source:
        reader = PdfReader(source)
        annotated = False
        pages_text = []
        extract = text and path.stat().st_size <= MAX_TEXT_FILE_SIZE
        for page in reader.pages:
            annotations = page.get("/Annots")
            for ref in annotations.get_object() if annotations is not None else []:
                annotation = ref.get_object()
                if annotation and annotation.get("/Subtype") in _MARKUP:
                    annotated = True
            if extract:
                pages_text.append(page.extract_text())
        return PDFInfo(hash_text("\n".join(pages_text), locale) if extract else None, annotated)


async def inspect_pdf(path: Path, locale: str = "en-US", *, text: bool = True) -> PDFInfo:
    """Read a PDF in a disposable worker, assuming possible markup on failure.

    ``text=False`` only inspects annotations, used when byte hashes already
    matched. The worker never reads a path supplied by an HTTP client: the
    merge service resolves the attachment's registered file in the store.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            __name__,
            str(path),
            locale,
            "text" if text else "annotations",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        logger.warning("Cannot start PDF merge worker", exc_info=True)
        return PDFInfo()
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), WORKER_TIMEOUT)
        if process.returncode != 0:
            return PDFInfo()
        data = json.loads(stdout)
        return PDFInfo(data["text_hash"], data["has_annotations"])
    except TimeoutError, ValueError, KeyError:
        return PDFInfo()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


def _worker() -> None:
    if sys.platform != "win32":
        import resource

        # The parent also enforces wall time and reaps the worker on cancellation.
        resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
        resource.setrlimit(resource.RLIMIT_AS, (768 * 1024**2, 768 * 1024**2))
    info = PDFInfo()
    # Any parser/library failure means possibly annotated. No document text or
    # file paths are emitted to request logs.
    with suppress(Exception):
        info = _inspect(Path(sys.argv[1]), sys.argv[2], text=sys.argv[3] == "text")
    print(json.dumps(asdict(info)))


if __name__ == "__main__":
    _worker()
