"""Real PDF parsing and the desktop's common-word fingerprint.

The PDFs are deliberately tiny and generated locally, with actual content
streams and annotation dictionaries, rather than mocked parser results.
"""

from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

from altero.services import pdfmerge

TEXT = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima"


def pdf_bytes(
    text: str = TEXT, *, subtype: str | None = None, password: str | None = None
) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)}),
        }
    )
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 30 700 Td ({text}) Tj ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    if subtype is not None:
        page[NameObject("/Annots")] = writer._add_object(
            ArrayObject(
                [
                    writer._add_object(
                        DictionaryObject(
                            {
                                NameObject("/Type"): NameObject("/Annot"),
                                NameObject("/Subtype"): NameObject(subtype),
                                NameObject("/Rect"): ArrayObject(
                                    [NumberObject(n) for n in (10, 10, 20, 20)]
                                ),
                            }
                        )
                    )
                ]
            )
        )
    if password is not None:
        writer.encrypt(password)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


async def test_reads_pdf_text_and_markup_in_a_worker(tmp_path: Path) -> None:
    path = tmp_path / "paper.pdf"
    path.write_bytes(pdf_bytes())
    info = await pdfmerge.inspect_pdf(path)
    assert info.text_hash == pdfmerge.hash_text(TEXT)
    assert info.has_annotations is False


@pytest.mark.parametrize(
    "subtype",
    [
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
    ],
)
async def test_every_desktop_markup_type_is_protected(tmp_path: Path, subtype: str) -> None:
    path = tmp_path / "annotated.pdf"
    path.write_bytes(pdf_bytes(subtype=subtype))
    info = await pdfmerge.inspect_pdf(path)
    assert info.has_annotations is True
    assert info.text_hash == pdfmerge.hash_text(TEXT)


@pytest.mark.parametrize("subtype", ["/Link", "/Widget", "/Popup", "/Movie", "/Screen"])
async def test_non_markup_annotations_do_not_prevent_merging(tmp_path: Path, subtype: str) -> None:
    path = tmp_path / "linked.pdf"
    path.write_bytes(pdf_bytes(subtype=subtype))
    info = await pdfmerge.inspect_pdf(path)
    assert info.has_annotations is False


async def test_annotations_on_later_pages_are_protected(tmp_path: Path) -> None:
    writer = PdfWriter()
    writer.append(PdfReader(BytesIO(pdf_bytes())))
    writer.append(PdfReader(BytesIO(pdf_bytes(subtype="/Ink"))))
    path = tmp_path / "two-pages.pdf"
    writer.write(path)
    assert (await pdfmerge.inspect_pdf(path)).has_annotations is True


@pytest.mark.parametrize("kind", ["missing", "malformed", "encrypted"])
async def test_an_unreadable_pdf_is_treated_as_annotated(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "unreadable.pdf"
    if kind == "malformed":
        path.write_bytes(b"%PDF-1.7\nnot a PDF")
    elif kind == "encrypted":
        path.write_bytes(pdf_bytes(password="secret"))
    info = await pdfmerge.inspect_pdf(path)
    assert info.has_annotations is True
    assert info.text_hash is None


async def test_worker_timeout_keeps_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "paper.pdf"
    path.write_bytes(pdf_bytes())
    monkeypatch.setattr(pdfmerge, "WORKER_TIMEOUT", 0.0001)
    info = await pdfmerge.inspect_pdf(path)
    assert info.has_annotations is True
    assert info.text_hash is None


def test_too_little_unique_text_has_no_fingerprint() -> None:
    assert pdfmerge.hash_text("alpha " * 100) is None
    assert pdfmerge.hash_text("") is None


def test_word_order_does_not_change_the_fingerprint() -> None:
    assert pdfmerge.hash_text(TEXT) == pdfmerge.hash_text(" ".join(reversed(TEXT.split())))
    assert pdfmerge.hash_text(TEXT) != pdfmerge.hash_text(TEXT.replace("alpha", "changed"))


def test_punctuation_is_removed_but_never_separates_words() -> None:
    assert pdfmerge.hash_text(TEXT.replace("alpha", "al-pha123")) == pdfmerge.hash_text(TEXT)
    assert pdfmerge.hash_text(TEXT.replace("alpha", "a l p h a")) != pdfmerge.hash_text(TEXT)


def test_frequencies_choose_fifty_words_not_fifty_occurrences() -> None:
    words = [f"word{chr(97 + i // 26)}{chr(97 + i % 26)}" for i in range(60)]
    text = " ".join(words)
    # The extra word is below the cut. Raising its frequency must bring it in.
    assert pdfmerge.hash_text(text) == pdfmerge.hash_text(" ".join(words[:50]))
    assert pdfmerge.hash_text(text + " " + words[-1]) != pdfmerge.hash_text(text)
