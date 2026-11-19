import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.schemas import ParsedSection
from app.services.chunking import chunk_sections, MAX_CHARS, OVERLAP_CHARS


def test_chunk_sections_termination_and_finite_chunks():
    # Construct a section with text significantly longer than MAX_CHARS (e.g. 50,000 characters)
    long_text = "This is a sentence in a research paper test document. " * 1000
    assert len(long_text) > MAX_CHARS * 10

    section = ParsedSection(
        section_type="method",
        text=long_text,
        page_start=1,
        page_end=5,
    )

    # Call chunk_sections
    chunks = chunk_sections(paper_id="test_paper_1", sections=[section])

    # Assert finite number of chunks produced
    assert isinstance(chunks, list)
    assert len(chunks) > 0
    # Expected chunk count approx len(long_text) / (MAX_CHARS - OVERLAP_CHARS)
    expected_approx = len(long_text) / (MAX_CHARS - OVERLAP_CHARS)
    assert len(chunks) <= expected_approx + 5

    # Assert that all chunks have valid fields and order
    for idx, c in enumerate(chunks):
        assert c.paper_id == "test_paper_1"
        assert c.section_type == "method"
        assert c.order == idx
        assert len(c.text) <= MAX_CHARS

    print(f"Unit Test Passed: Generated {len(chunks)} chunks for {len(long_text)} chars of text.")


if __name__ == "__main__":
    test_chunk_sections_termination_and_finite_chunks()


def test_references_are_not_indexed():
    secs = [ParsedSection(section_type="results", text="Real findings here.", page_start=1, page_end=1),
            ParsedSection(section_type="references", text="[1] Smith, J. 2020. Some Journal.", page_start=2, page_end=2)]
    chunks = chunk_sections("p", secs)
    assert [c.section_type for c in chunks] == ["results"]


def test_cuts_land_on_sentence_boundaries_and_never_mid_word():
    sentence = "Gradient descent converges under convexity assumptions. "
    text = sentence * 80
    chunks = chunk_sections("p", [ParsedSection(section_type="method", text=text, page_start=1, page_end=1)])
    assert len(chunks) > 2
    for c in chunks[:-1]:
        assert c.text.endswith("."), c.text[-30:]
        assert len(c.text) <= MAX_CHARS


def test_tiny_tail_is_merged():
    text = ("Word " * 270).strip()          # ~1350 chars: one chunk + a few words of tail
    chunks = chunk_sections("p", [ParsedSection(section_type="other", text=text, page_start=1, page_end=1)])
    assert all(len(c.text) >= 250 for c in chunks)


def test_chunks_keep_section_pages_and_global_order():
    secs = [ParsedSection(section_type="abstract", text="A. " * 10, page_start=1, page_end=1),
            ParsedSection(section_type="results", text="B " * 1500, page_start=3, page_end=4)]
    chunks = chunk_sections("p", secs)
    assert [c.order for c in chunks] == list(range(len(chunks)))
    assert chunks[0].page_start == 1 and chunks[-1].page_start == 3 and chunks[-1].page_end == 4
