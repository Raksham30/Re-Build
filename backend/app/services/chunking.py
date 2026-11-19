"""
Section-aware chunking.

  * Chunks never cross a section boundary, so section_type / page range on a chunk is exact.
  * The references section is NOT indexed: bibliography lines match almost any query on names
    and venues and crowd out real evidence.
  * Cuts prefer a sentence boundary, then a word boundary -- never mid-word.
  * Consecutive chunks of a section overlap a little so a fact straddling a cut stays retrievable.
  * A tiny trailing fragment is merged into the previous chunk when it fits.

Sizes are in characters (~4 chars per token): 1400 chars is roughly 350 tokens, a good unit for
both embedding quality and prompt budget.
"""
import re
import uuid

from app.schemas import ParsedSection, Chunk

MAX_CHARS = 1400
OVERLAP_CHARS = 200
MIN_TAIL_CHARS = 250            # a final piece shorter than this is merged into the previous chunk
SENTENCE_WINDOW = 300           # how far back from the ideal cut we look for a sentence end
NOT_INDEXED = {"references"}
MAX_CHUNKS_PER_PAPER = 2000

_SENTENCE_END = re.compile(r"[.!?][\"')\]]?\s")


def _snap_to_boundary(text: str, ideal_end: int) -> int:
    """Moves a cut left to the nearest sentence end (within SENTENCE_WINDOW), else the nearest
    word boundary (within 80 chars), else leaves it. Returns the exclusive end index."""
    if ideal_end >= len(text) or text[ideal_end].isspace():
        return ideal_end
    window_start = max(0, ideal_end - SENTENCE_WINDOW)
    last = None
    for m in _SENTENCE_END.finditer(text, window_start, ideal_end):
        last = m
    if last is not None and last.end() - window_start > SENTENCE_WINDOW // 3:
        return last.end()
    earliest = max(0, ideal_end - 80)
    idx = text.rfind(" ", earliest, ideal_end)
    if idx == -1:
        idx = text.rfind("\n", earliest, ideal_end)
    return idx + 1 if idx != -1 else ideal_end


def _split_section(text: str) -> list[str]:
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = _snap_to_boundary(text, min(start + MAX_CHARS, len(text)))
        if end <= start:
            end = min(start + MAX_CHARS, len(text))
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= len(text):
            break
        new_start = max(start + 1, end - OVERLAP_CHARS)
        if new_start < len(text) and not text[new_start].isspace():
            next_space = text.find(" ", new_start, min(new_start + 80, len(text)))
            if next_space != -1:
                new_start = next_space + 1
        start = new_start
    # merge a tiny tail into its predecessor if it still fits
    if len(pieces) >= 2 and len(pieces[-1]) < MIN_TAIL_CHARS and len(pieces[-2]) + 1 + len(pieces[-1]) <= MAX_CHARS:
        pieces[-2] = pieces[-2] + " " + pieces[-1]
        pieces.pop()
    return pieces


def chunk_sections(paper_id: str, sections: list[ParsedSection]) -> list[Chunk]:
    if OVERLAP_CHARS >= MAX_CHARS:
        raise ValueError("OVERLAP_CHARS must be smaller than MAX_CHARS")

    chunks: list[Chunk] = []
    for section in sections:
        if section.section_type in NOT_INDEXED:
            continue
        text = section.text or ""
        if not text.strip():
            continue
        for piece in _split_section(text):
            if len(chunks) >= MAX_CHUNKS_PER_PAPER:
                return chunks
            chunks.append(Chunk(
                chunk_id=str(uuid.uuid4()), paper_id=paper_id, text=piece,
                section_type=section.section_type, page_start=section.page_start,
                page_end=section.page_end, order=len(chunks),
            ))
    return chunks
