"""
Layout-aware PDF parsing with PyMuPDF (local, no per-page cost).

Produces a list of ParsedSection with exact page ranges -- that is what
makes page-level citations possible later.

Per page we read text lines in reading order (multi-column aware), then:
  * drop running headers/footers (short lines repeating near the top/bottom
    of most pages) and bare page numbers
  * detect section headings (Abstract, 1 Introduction, II. RELATED WORK, ...)
    including IEEE-style inline "Abstract—text" openers
  * re-join words hyphenated across line breaks
Scanned PDFs (no text layer) raise a clear error; OCR is not included.
"""
from __future__ import annotations
import re
from collections import Counter
from dataclasses import dataclass

from app.schemas import ParsedSection, SectionType

_NUM = r"(\d+(\.\d+)*\.?\s*|[ivxlcdm]+\.\s*|[ivxlcdm]+\s+)?"   # "1", "2.1.", "IV.", "ii "
HEADING_PATTERNS: list[tuple[SectionType, str]] = [
    ("abstract", rf"^\s*{_NUM}abstract\s*:?\s*$"),
    ("introduction", rf"^\s*{_NUM}introduction\s*:?\s*$"),
    ("related_work", rf"^\s*{_NUM}(related work|literature review|background|prior work)\s*:?\s*$"),
    ("method", rf"^\s*{_NUM}(method|methods|methodology|approach|model|proposed method|proposed approach|system design|design)\s*:?\s*$"),
    ("experiments", rf"^\s*{_NUM}(experiments?|experimental setup|experimental results and analysis|evaluation|case study)\s*:?\s*$"),
    ("results", rf"^\s*{_NUM}(results?|findings|results and discussion)\s*:?\s*$"),
    ("discussion", rf"^\s*{_NUM}discussion\s*:?\s*$"),
    ("limitations", rf"^\s*{_NUM}(limitations?|threats to validity)\s*:?\s*$"),
    ("conclusion", rf"^\s*{_NUM}(conclusions?|conclusions? and future work|future work|concluding remarks)\s*:?\s*$"),
    ("references", rf"^\s*{_NUM}(references|bibliography|acknowledg(e)?ments?)\s*:?\s*$"),
]
# "Abstract— We propose ..." / "Abstract. We ..." (heading and text on the same line)
_INLINE_ABSTRACT = re.compile(r"^\s*abstract\s*[—–\-:.]\s*(?P<rest>\S.*)$", re.IGNORECASE)
_PAGE_NUMBER = re.compile(r"^\s*(page\s+)?\d{1,4}(\s*(/|of)\s*\d{1,4})?\s*$", re.IGNORECASE)
_MARGIN_FRACTION = 0.09      # top/bottom band considered header/footer area


@dataclass
class _Line:
    text: str
    page: int
    y0: float
    y1: float
    page_height: float


def _classify_heading(line: str) -> SectionType | None:
    clean = line.strip().lower()
    for section_type, pattern in HEADING_PATTERNS:
        if re.match(pattern, clean):
            return section_type
    return None


def _extract_lines(doc) -> list[_Line]:
    lines: list[_Line] = []
    for page_no, page in enumerate(doc, start=1):
        height = page.rect.height
        # sort=True returns blocks in reading order (top-to-bottom, then column-wise)
        for block in page.get_text("dict", sort=True)["blocks"]:
            if block.get("type") != 0:
                continue
            for ln in block["lines"]:
                text = "".join(s["text"] for s in ln["spans"]).strip()
                if text:
                    lines.append(_Line(text, page_no, ln["bbox"][1], ln["bbox"][3], height))
    return lines


def _normalise_for_repeat(text: str) -> str:
    return re.sub(r"\d+", "#", text.strip().lower())


def _drop_running_headers_footers(lines: list[_Line], num_pages: int) -> list[_Line]:
    in_margin = lambda l: l.y1 <= l.page_height * _MARGIN_FRACTION or l.y0 >= l.page_height * (1 - _MARGIN_FRACTION)
    repeating: set[str] = set()
    if num_pages >= 3:
        pages_seen: dict[str, set[int]] = {}
        for l in lines:
            if in_margin(l):
                pages_seen.setdefault(_normalise_for_repeat(l.text), set()).add(l.page)
        repeating = {t for t, pages in pages_seen.items() if len(pages) >= max(3, num_pages // 2)}
    kept = []
    for l in lines:
        if in_margin(l) and (_normalise_for_repeat(l.text) in repeating or _PAGE_NUMBER.match(l.text)):
            continue
        kept.append(l)
    return kept


def _join_dehyphenated(texts: list[str]) -> str:
    out: list[str] = []
    for t in texts:
        if out and re.search(r"[A-Za-z]{2}-$", out[-1]) and t[:1].islower():
            out[-1] = out[-1][:-1] + t        # "classi-" + "fication" -> "classification"
        else:
            out.append(t)
    return "\n".join(out)


def parse_pdf(file_path: str) -> tuple[list[ParsedSection], int]:
    import pymupdf  # PyMuPDF

    try:
        doc = pymupdf.open(file_path)
    except Exception as e:
        raise ValueError(f"Could not open PDF: {e}") from e
    with doc:
        num_pages = len(doc)
        lines = _drop_running_headers_footers(_extract_lines(doc), num_pages)

    if not "".join(l.text for l in lines).strip():
        raise ValueError(
            "No extractable text in this PDF (it looks scanned/image-only). "
            "OCR is not supported -- upload a PDF with a text layer."
        )

    sections: list[ParsedSection] = []
    current_type: SectionType = "title"
    buffer: list[str] = []
    start_page = lines[0].page
    last_page = lines[0].page

    def flush():
        text = _join_dehyphenated(buffer).strip()
        if text:
            sections.append(ParsedSection(
                section_type=current_type, text=text, page_start=start_page, page_end=last_page,
            ))

    for l in lines:
        heading = _classify_heading(l.text)
        inline_rest = None
        if heading is None:
            m = _INLINE_ABSTRACT.match(l.text)
            if m:
                heading, inline_rest = "abstract", m.group("rest")

        if heading and heading != current_type:
            flush()
            current_type, buffer, start_page = heading, [], l.page
            if inline_rest:
                buffer.append(inline_rest)
        elif heading is None:
            if not buffer:
                start_page = l.page
            buffer.append(l.text)
        # (a repeated heading of the current type, e.g. "Results" again, is dropped)
        last_page = l.page

    flush()
    if not sections:   # defensive: text existed but only headings were found
        full = "\n".join(l.text for l in lines)
        sections = [ParsedSection(section_type="other", text=full, page_start=1, page_end=num_pages)]
    return sections, num_pages
