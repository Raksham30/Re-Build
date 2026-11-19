"""PyMuPDF parsing: headings, page ranges, header/footer removal, dehyphenation, errors."""
import pymupdf as fitz
import pytest

from app.services import parsing


def _make_pdf(path, pages):
    doc = fitz.open()
    for header, body_lines in pages:
        page = doc.new_page()
        page.insert_text((72, 30), header, fontsize=9)               # running header
        y = 100
        for line in body_lines:
            page.insert_text((72, y), line, fontsize=11)
            y += 16
        page.insert_text((300, 820), "Journal of Tests 2026", fontsize=9)   # running footer
    doc.save(path)
    doc.close()


@pytest.fixture()
def pdf(tmp_path):
    p = str(tmp_path / "paper.pdf")
    _make_pdf(p, [
        ("RUNNING HEADER 1", ["A Study of Things", "Abstract", "We study classi-", "fication of things."]),
        ("RUNNING HEADER 2", ["1 Introduction", "Things matter.", "2. Related Work", "Others studied things."]),
        ("RUNNING HEADER 3", ["III. METHODS", "We did stuff.", "4 Results", "It worked."]),
        ("RUNNING HEADER 4", ["5 Conclusion", "Done.", "References", "[1] Someone."]),
    ])
    return p


def test_sections_types_and_pages(pdf):
    sections, pages = parsing.parse_pdf(pdf)
    assert pages == 4
    by_type = {s.section_type: s for s in sections}
    assert list(by_type) == ["title", "abstract", "introduction", "related_work",
                             "method", "results", "conclusion", "references"]
    assert by_type["title"].text == "A Study of Things"
    assert by_type["introduction"].page_start == 2 and by_type["introduction"].page_end == 2
    assert by_type["method"].page_start == 3
    assert by_type["references"].page_start == 4


def test_running_headers_footers_removed_and_dehyphenated(pdf):
    sections, _ = parsing.parse_pdf(pdf)
    all_text = " ".join(s.text for s in sections)
    assert "RUNNING HEADER" not in all_text and "Journal of Tests" not in all_text
    assert "classification of things." in all_text


def test_inline_abstract(tmp_path):
    p = str(tmp_path / "ieee.pdf")
    _make_pdf(p, [("", ["Title Here", "Abstract- We propose a thing.", "I. INTRODUCTION", "Intro text."])])
    sections, _ = parsing.parse_pdf(p)
    abstract = next(s for s in sections if s.section_type == "abstract")
    assert abstract.text == "We propose a thing."
    assert any(s.section_type == "introduction" for s in sections)


def test_scanned_pdf_gives_clear_error(tmp_path):
    p = str(tmp_path / "scan.pdf")
    doc = fitz.open(); doc.new_page(); doc.save(p); doc.close()
    with pytest.raises(ValueError, match="No extractable text"):
        parsing.parse_pdf(p)


def test_not_a_pdf(tmp_path):
    p = tmp_path / "x.pdf"; p.write_bytes(b"not a pdf")
    with pytest.raises(ValueError):
        parsing.parse_pdf(str(p))
