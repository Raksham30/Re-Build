"""
Chunk index on Postgres + pgvector.

Contract (unchanged for callers):
  index_chunks(chunks)                      embed + upsert
  delete_paper_chunks(paper_ids)
  search_chunks(query, paper_ids, top_k)    -> list[dict] with chunk_id, paper_id, text,
                                               section_type, page_start, page_end, order, score
  search_chunks_by_paper(query, paper_ids)  -> top chunks for EACH paper in one query

Retrieval is HYBRID by default (settings.hybrid_search):
  dense    pgvector cosine similarity      -> good at meaning / paraphrase
  keyword  Postgres full-text (ts_rank_cd) -> good at exact terms: acronyms, dataset and
                                              method names, numbers
fused with Reciprocal Rank Fusion (RRF), which needs no score calibration between the two.
Note: ts_rank_cd is a term-frequency / proximity ranker, BM25-like but not literal BM25.
`score` in results is the fused RRF score (or cosine similarity when hybrid is off).
"""
from __future__ import annotations
import re

from app.config import get_settings
from app.db import connection
from app.schemas import Chunk
from app.services.embeddings import embed_texts, embedding_dim

_COLUMNS = "chunk_id, paper_id, text, section_type, page_start, page_end, chunk_order"


RRF_K = 60          # standard RRF constant
POOL_FACTOR = 4     # candidates fetched per ranker = top_k * POOL_FACTOR


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]


def _vec(v) -> str:
    return "[" + ",".join(f"{float(x):.8g}" for x in v) + "]"


def _check_dim(vectors) -> None:
    dim = embedding_dim()
    for v in vectors:
        if len(v) != dim:
            raise RuntimeError(
                f"Embedding has {len(v)} dimensions but GEMINI_EMBEDDING_DIM={dim}; "
                "the chunks table and the embedding model must agree."
            )


def _row_to_chunk_dict(r: dict) -> dict:
    return {
        "chunk_id": r["chunk_id"], "paper_id": r["paper_id"], "text": r["text"],
        "section_type": r["section_type"], "page_start": r["page_start"],
        "page_end": r["page_end"], "order": r["chunk_order"], "score": float(r["score"]),
    }


def _embedding_input(c: Chunk, doc_title: str | None) -> str:
    """Text that gets embedded. A "Paper title - Section" header gives every chunk the
    document-level context it would otherwise lack ("the results show..." of WHAT?).
    Only the embedding sees the header; the stored/displayed text stays clean."""
    if not doc_title:
        return c.text
    return f"{doc_title} - {c.section_type.replace('_', ' ')}\n{c.text}"


def index_chunks(chunks: list[Chunk], doc_title: str | None = None) -> None:
    if not chunks:
        return
    vectors = embed_texts([_embedding_input(c, doc_title) for c in chunks])
    _check_dim(vectors)
    rows = [
        (c.chunk_id, c.paper_id, c.text, c.section_type, c.page_start, c.page_end, c.order, _vec(v))
        for c, v in zip(chunks, vectors)
    ]
    with connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO chunks (chunk_id, paper_id, text, section_type, page_start,
                                    page_end, chunk_order, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector)
                ON CONFLICT (chunk_id) DO UPDATE SET
                    text = EXCLUDED.text, section_type = EXCLUDED.section_type,
                    page_start = EXCLUDED.page_start, page_end = EXCLUDED.page_end,
                    chunk_order = EXCLUDED.chunk_order, embedding = EXCLUDED.embedding
                """,
                rows,
            )


def delete_paper_chunks(paper_ids: list[str]) -> None:
    """Removes every indexed chunk belonging to the given papers."""
    if not paper_ids:
        return
    with connection() as conn:
        conn.execute("DELETE FROM chunks WHERE paper_id = ANY (%s)", (list(paper_ids),))


def _or_tsquery(query: str) -> str | None:
    """'what datasets did BERT use?' -> 'what | datasets | did | BERT | use' (stop words are dropped by
    Postgres). OR semantics: natural-language questions rarely contain ALL the words of a passage."""
    words = list(dict.fromkeys(w.lower() for w in re.findall(r"[A-Za-z0-9]{2,}", query)))[:24]
    return " | ".join(words) or None


def _dense_rows(qv: str, paper_ids, limit: int, per_paper: bool = False) -> list[dict]:
    where, params = "", [qv]
    if paper_ids is not None:
        where, params = " WHERE paper_id = ANY (%s)", [qv, list(paper_ids)]
    if per_paper:
        sql = (f"SELECT * FROM (SELECT {_COLUMNS}, 1 - (embedding <=> %s::vector) AS score, "
               f"ROW_NUMBER() OVER (PARTITION BY paper_id ORDER BY embedding <=> %s::vector) AS rn "
               f"FROM chunks{where}) r WHERE rn <= %s")
        params = [qv, qv] + params[1:] + [limit]
    else:
        sql = (f"SELECT {_COLUMNS}, 1 - (embedding <=> %s::vector) AS score FROM chunks{where} "
               f"ORDER BY embedding <=> %s::vector LIMIT %s")
        params = params + [qv, limit]
    with connection() as conn:
        return conn.execute(sql, params).fetchall()


def _keyword_rows(query: str, paper_ids, limit: int, per_paper: bool = False) -> list[dict]:
    tsq = _or_tsquery(query)
    if not tsq:
        return []
    where, params = "tsv @@ q", [tsq]
    if paper_ids is not None:
        where, params = "paper_id = ANY (%s) AND tsv @@ q", [tsq, list(paper_ids)]
    if per_paper:
        sql = (f"SELECT * FROM (SELECT {_COLUMNS}, ts_rank_cd(tsv, q, 1) AS score, "
               f"ROW_NUMBER() OVER (PARTITION BY paper_id ORDER BY ts_rank_cd(tsv, q, 1) DESC) AS rn "
               f"FROM chunks, to_tsquery('english', %s) q WHERE {where}) r WHERE rn <= %s")
        params = params + [limit]
    else:
        sql = (f"SELECT {_COLUMNS}, ts_rank_cd(tsv, q, 1) AS score FROM chunks, "
               f"to_tsquery('english', %s) q WHERE {where} ORDER BY score DESC LIMIT %s")
        params = params + [limit]
    with connection() as conn:
        return conn.execute(sql, params).fetchall()


def _rrf(*ranked: list[dict]) -> list[dict]:
    """Reciprocal Rank Fusion over best-first lists of rows; returns rows best-first with score=fused."""
    fused: dict[str, float] = {}
    rows: dict[str, dict] = {}
    for lst in ranked:
        for rank, row in enumerate(lst, start=1):
            fused[row["chunk_id"]] = fused.get(row["chunk_id"], 0.0) + 1.0 / (RRF_K + rank)
            rows.setdefault(row["chunk_id"], row)
    out = []
    for cid in sorted(fused, key=fused.get, reverse=True):
        out.append({**rows[cid], "score": fused[cid]})
    return out


def search_chunks(query: str, paper_ids: list[str] | None, top_k: int = 8,
                  query_vector=None, hybrid: bool | None = None) -> list[dict]:
    # An EMPTY list means "no papers in scope" (e.g. a workspace whose papers were
    # all deleted) -- it must not fall through to an unfiltered, cross-workspace search.
    if paper_ids is not None and len(paper_ids) == 0:
        return []
    use_hybrid = get_settings().hybrid_search if hybrid is None else hybrid
    vector = query_vector if query_vector is not None else embed_query(query)
    _check_dim([vector])
    qv = _vec(vector)

    if not use_hybrid:
        return [_row_to_chunk_dict(r) for r in _dense_rows(qv, paper_ids, top_k)]
    pool = max(top_k * POOL_FACTOR, 20)
    fused = _rrf(_dense_rows(qv, paper_ids, pool), _keyword_rows(query, paper_ids, pool))
    return [_row_to_chunk_dict(r) for r in fused[:top_k]]


def search_chunks_by_paper(query: str, paper_ids: list[str], per_paper_k: int = 3,
                           hybrid: bool | None = None) -> list[dict]:
    """Top chunks for EACH paper (query embedded once). Guarantees every selected paper is
    represented -- a plain top-k over all papers can return chunks from only one, which breaks
    compare/contrast and 'summarise each paper' questions.
    Results come back grouped in `paper_ids` order, best chunk first within each paper."""
    if not paper_ids:
        return []
    use_hybrid = get_settings().hybrid_search if hybrid is None else hybrid
    vector = embed_query(query)
    _check_dim([vector])
    qv = _vec(vector)

    pool = max(per_paper_k * POOL_FACTOR, 8) if use_hybrid else per_paper_k
    dense = sorted(_dense_rows(qv, paper_ids, pool, per_paper=True), key=lambda r: (r["paper_id"], r["rn"]))
    by_paper: dict[str, list[dict]] = {}
    if use_hybrid:
        kw = sorted(_keyword_rows(query, paper_ids, pool, per_paper=True), key=lambda r: (r["paper_id"], r["rn"]))
        for pid in paper_ids:
            fused = _rrf([r for r in dense if r["paper_id"] == pid], [r for r in kw if r["paper_id"] == pid])
            by_paper[pid] = fused[:per_paper_k]
    else:
        for pid in paper_ids:
            by_paper[pid] = [r for r in dense if r["paper_id"] == pid]
    return [_row_to_chunk_dict(r) for pid in paper_ids for r in by_paper.get(pid, [])]
