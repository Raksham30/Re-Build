"""pgvector chunk index: ranking, scoping, per-paper retrieval, delete, dimension guard."""
import os
import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")

# 3-dim "embeddings": x ~ cats, y ~ dogs, z ~ birds
VOCAB = {"cat": [1.0, 0.0, 0.0], "dog": [0.0, 1.0, 0.0], "bird": [0.0, 0.0, 1.0]}


def _embed(texts):
    out = []
    for t in texts:
        v = [0.01, 0.01, 0.01]
        for word, vec in VOCAB.items():
            if word in t.lower():
                v = [a + b for a, b in zip(v, vec)] if v != [0.01] * 3 else list(vec)
        out.append(v)
    return out


@pytest.fixture()
def ix(monkeypatch):
    from app.schemas import Paper
    from app.services import indexing, storage
    monkeypatch.setattr(indexing, "embed_texts", _embed)
    ws = storage.create_workspace("u", "w").workspace_id
    for pid in ("p1", "p2", "p3"):
        storage.save_paper(Paper(paper_id=pid, workspace_id=ws, filename=f"{pid}.pdf"))
    return indexing


def _chunk(cid, pid, text, order=0):
    from app.schemas import Chunk
    return Chunk(chunk_id=cid, paper_id=pid, text=text, section_type="results",
                 page_start=2, page_end=3, order=order)


def test_ranking_and_result_shape(ix):
    ix.index_chunks([_chunk("a", "p1", "the cat sat"), _chunk("b", "p1", "the dog ran", 1),
                     _chunk("c", "p2", "a bird flew")])
    hits = ix.search_chunks("cat", ["p1", "p2"], top_k=2)
    assert [h["chunk_id"] for h in hits][0] == "a"
    assert hits[0]["score"] >= hits[1]["score"]
    assert set(hits[0]) == {"chunk_id", "paper_id", "text", "section_type", "page_start",
                            "page_end", "order", "score"}
    assert hits[0]["page_start"] == 2 and hits[0]["section_type"] == "results"


def test_scoping_and_empty_scope(ix):
    ix.index_chunks([_chunk("a", "p1", "cat"), _chunk("c", "p2", "cat too")])
    assert {h["paper_id"] for h in ix.search_chunks("cat", ["p2"])} == {"p2"}
    assert ix.search_chunks("cat", []) == []          # empty scope must NOT search everything
    assert len(ix.search_chunks("cat", None)) == 2


def test_search_by_paper_represents_every_paper_in_order(ix):
    ix.index_chunks([_chunk("a1", "p1", "cat one"), _chunk("a2", "p1", "cat two", 1),
                     _chunk("b1", "p2", "dog only"), _chunk("c1", "p3", "bird only")])
    hits = ix.search_chunks_by_paper("cat", ["p3", "p1", "p2"], per_paper_k=1)
    assert [h["paper_id"] for h in hits] == ["p3", "p1", "p2"]     # paper_ids order, 1 each
    assert hits[1]["chunk_id"] in ("a1", "a2")


def test_upsert_and_delete(ix):
    ix.index_chunks([_chunk("a", "p1", "cat")])
    ix.index_chunks([_chunk("a", "p1", "dog now")])               # same id -> replaced
    hits = ix.search_chunks("dog", ["p1"])
    assert len(hits) == 1 and hits[0]["text"] == "dog now"
    ix.delete_paper_chunks(["p1"])
    assert ix.search_chunks("dog", ["p1"]) == []


def test_wrong_dimension_is_a_clear_error(ix, monkeypatch):
    monkeypatch.setattr(ix, "embed_texts", lambda texts: [[1.0, 0.0] for _ in texts])
    with pytest.raises(RuntimeError, match="dimensions"):
        ix.index_chunks([_chunk("a", "p1", "cat")])


def test_deleting_paper_cascades_chunks(ix):
    from app.services import storage
    ix.index_chunks([_chunk("a", "p1", "cat")])
    ws = storage.list_workspaces("u")[0].workspace_id
    storage.delete_paper(ws, "p1")
    assert ix.search_chunks("cat", None) == []


def test_hybrid_finds_exact_term_that_dense_misses(ix, monkeypatch):
    """A rare token (acronym) the embedding can't see is rescued by the keyword half."""
    # every chunk gets the SAME vector, so dense ranking is a coin flip; only keywords can tell them apart
    monkeypatch.setattr(ix, "embed_texts", lambda texts: [[1.0, 0.0, 0.0] for _ in texts])
    ix.index_chunks([_chunk("a", "p1", "general discussion of training"),
                     _chunk("b", "p1", "we evaluate on the XQ7-ZETA benchmark", 1),
                     _chunk("c", "p2", "another unrelated paragraph")])
    hybrid = ix.search_chunks("results on XQ7 ZETA", ["p1", "p2"], top_k=3, hybrid=True)
    assert hybrid[0]["chunk_id"] == "b"


def test_hybrid_off_is_pure_dense(ix):
    ix.index_chunks([_chunk("a", "p1", "cat"), _chunk("b", "p1", "dog", 1)])
    hits = ix.search_chunks("cat", ["p1"], top_k=2, hybrid=False)
    assert hits[0]["chunk_id"] == "a" and 0.99 < hits[0]["score"] <= 1.0   # raw cosine


def test_hybrid_by_paper_still_represents_every_paper(ix):
    ix.index_chunks([_chunk("a1", "p1", "cat one"), _chunk("b1", "p2", "dog only"), _chunk("c1", "p3", "bird only")])
    hits = ix.search_chunks_by_paper("cat", ["p3", "p1", "p2"], per_paper_k=1, hybrid=True)
    assert [h["paper_id"] for h in hits] == ["p3", "p1", "p2"]


def test_context_header_is_embedded_but_not_stored(ix, monkeypatch):
    seen = []
    monkeypatch.setattr(ix, "embed_texts", lambda texts: seen.extend(texts) or [[1.0, 0.0, 0.0] for _ in texts])
    ix.index_chunks([_chunk("a", "p1", "the results show gains")], doc_title="Cat Paper")
    assert seen == ["Cat Paper - results\nthe results show gains"]
    assert ix.search_chunks("gains", ["p1"], top_k=1, query_vector=[1.0, 0.0, 0.0])[0]["text"] == "the results show gains"
