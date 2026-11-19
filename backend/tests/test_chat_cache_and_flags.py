"""Chat answer caching end-to-end (fakeredis + real Postgres) and the flags API."""
import os
import fakeredis
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")

UID = "cache-user"


@pytest.fixture()
def env(monkeypatch):
    for v in ("S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "FIREBASE_SERVICE_ACCOUNT_PATH"):
        monkeypatch.setenv(v, "")
    monkeypatch.setenv("REDIS_URL", "redis://fake")
    from app.config import get_settings
    get_settings.cache_clear()
    from app.services import cache, indexing, generation, storage
    from app.schemas import Chunk, Paper, StructuredExtraction
    cache.reset(); cache.use_client(fakeredis.FakeRedis(decode_responses=True))

    emb_calls, gen_calls = [], []
    def emb(texts):
        emb_calls.append(list(texts))
        return [[1.0, 0.0, 0.0] if "cat" in t.lower() else [0.0, 1.0, 0.0] for t in texts]
    monkeypatch.setattr(indexing, "embed_texts", emb)
    def gen(system, user, max_tokens=600, task=None):
        gen_calls.append(task)
        return "Cats nap."
    monkeypatch.setattr(generation, "generate", gen)

    ws = storage.create_workspace(UID, "w").workspace_id
    storage.save_paper(Paper(paper_id="p1", workspace_id=ws, filename="p1.pdf", title="Cats", status="indexed"))
    storage.save_extraction(ws, "p1", StructuredExtraction(title="Cats"))
    indexing.index_chunks([Chunk(chunk_id="c1", paper_id="p1", text="cats nap a lot", section_type="results",
                                 page_start=1, page_end=1, order=0)])
    from app.main import app
    from app.auth import get_current_uid
    app.dependency_overrides[get_current_uid] = lambda: UID
    yield TestClient(app), ws, emb_calls, gen_calls, cache
    app.dependency_overrides.clear()
    cache.reset(); get_settings.cache_clear()


def _ask(client, ws, q):
    r = client.post(f"/workspaces/{ws}/chat/ask", json={"question": q})
    assert r.status_code == 200, r.text
    return r.json()


def test_exact_semantic_and_invalidation(env):
    client, ws, emb_calls, gen_calls, cache = env
    first = _ask(client, ws, "What do cats do?")
    assert len(gen_calls) == 1 and first["citations"][0]["paper_title"] == "Cats"

    again = _ask(client, ws, "  what do CATS do ")             # exact (normalised) hit: no new generation
    assert again == first and len(gen_calls) == 1

    para = _ask(client, ws, "Tell me about cat behaviour")       # different text, same embedding -> semantic hit
    assert para == first and len(gen_calls) == 1
    assert cache.stats()["hit_exact"] >= 1 and cache.stats()["hit_semantic"] == 1

    cache.bump_corpus_version(ws)                                # e.g. a paper was uploaded/deleted
    _ask(client, ws, "What do cats do?")
    assert len(gen_calls) == 2                                   # stale answer not reused


def test_cache_is_per_workspace(env):
    client, ws, _, gen_calls, _ = env
    from app.services import storage
    other = storage.create_workspace(UID, "other").workspace_id
    _ask(client, ws, "What do cats do?")
    r = client.post(f"/workspaces/{other}/chat/ask", json={"question": "What do cats do?"}).json()
    assert r["citations"] == [] and len(gen_calls) == 1          # empty workspace: no leak, no generation


def test_flags_api(env):
    client, ws, *_ = env
    from app.services import storage
    storage.save_flag(ws, {"type": "contradiction", "paper_ids_involved": ["p1"], "payload": {"x": 1}})
    out = client.get(f"/workspaces/{ws}/flags").json()
    assert out["new_count"] == 1 and out["flags"][0]["payload"] == {"x": 1}
    fid = out["flags"][0]["flag_id"]
    assert client.post(f"/workspaces/{ws}/flags/{fid}/status", json={"status": "seen"}).status_code == 200
    assert client.get(f"/workspaces/{ws}/flags").json()["new_count"] == 0
    client.post(f"/workspaces/{ws}/flags/{fid}/status", json={"status": "dismissed"})
    assert client.get(f"/workspaces/{ws}/flags").json()["flags"] == []
    assert len(client.get(f"/workspaces/{ws}/flags?include_dismissed=true").json()["flags"]) == 1
    assert client.post(f"/workspaces/{ws}/flags/nope/status", json={"status": "seen"}).status_code == 404


def test_production_refuses_insecure_config(monkeypatch):
    import importlib, app.main as m
    from app.config import get_settings
    monkeypatch.setenv("APP_ENV", "production"); monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT_PATH", "")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="FIREBASE"):
        importlib.reload(m)
    monkeypatch.setenv("APP_ENV", "development"); get_settings.cache_clear()
    importlib.reload(m)
