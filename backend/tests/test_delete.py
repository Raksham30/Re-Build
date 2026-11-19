"""
Delete paper / delete workspace. Runs fully offline: forces S3/Firebase off (even if a real .env exists), uses a temp data dir, and fakes
embeddings -- no network, no Gemini quota.
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

UID = "delete_test_user"
OTHER_UID = "someone_else"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    for var in (
        "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_ENDPOINT_URL",
        "FIREBASE_SERVICE_ACCOUNT_PATH",
    ):
        monkeypatch.setenv(var, "")
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LOCAL_UPLOAD_DIR", str(tmp_path / "uploads"))

    from app.config import get_settings
    get_settings.cache_clear()

    from app.services import indexing
    monkeypatch.setattr(indexing, "embed_texts", lambda texts: [[1.0, 0.0, 0.0] for _ in texts])

    from app.main import app
    from app.auth import get_current_uid
    current = {"uid": UID}
    app.dependency_overrides[get_current_uid] = lambda: current["uid"]
    c = TestClient(app)
    c.current = current
    yield c
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _add_paper(ws_id, paper_id, text="hello", title=""):
    """Seeds a paper the way the upload endpoint would (record + file + chunks + extraction)."""
    from app.schemas import Chunk, Paper, StructuredExtraction
    from app.services import file_storage, indexing, storage

    file_storage.save_pdf(ws_id, paper_id, b"%PDF-1.4 fake")
    storage.save_paper(Paper(paper_id=paper_id, workspace_id=ws_id, filename=f"{paper_id}.pdf", title=title, status="indexed"))
    storage.save_extraction(ws_id, paper_id, StructuredExtraction(title=paper_id))
    indexing.index_chunks([
        Chunk(chunk_id=f"{paper_id}-0", paper_id=paper_id, text=text, section_type="other",
              page_start=1, page_end=1, order=0),
    ])


def _chunk_paper_ids():
    from app.services import indexing
    from app.db import connection
    with connection() as conn:
        rows = conn.execute("SELECT paper_id FROM chunks").fetchall()
    return sorted(r["paper_id"] for r in rows)


def test_delete_paper_removes_record_file_and_chunks_only_for_that_paper(client):
    ws = client.post("/workspaces", json={"name": "ws"}).json()["workspace_id"]
    _add_paper(ws, "aaaa1111")
    _add_paper(ws, "bbbb2222")

    from app.services import storage
    storage.save_flag(ws, {"type": "gap", "paper_ids_involved": ["aaaa1111", "bbbb2222"], "payload": {}})

    assert client.delete(f"/workspaces/{ws}/papers/aaaa1111").status_code == 204

    remaining = [p["paper_id"] for p in client.get(f"/workspaces/{ws}/papers").json()]
    assert remaining == ["bbbb2222"]
    assert _chunk_paper_ids() == ["bbbb2222"]
    assert storage.get_extraction(ws, "aaaa1111") is None
    assert storage.get_extraction(ws, "bbbb2222") is not None
    assert storage.list_flags(ws, include_dismissed=True) == []  # flag referenced the deleted paper
    assert not os.path.exists(os.path.join(os.environ["LOCAL_UPLOAD_DIR"], ws, "aaaa1111.pdf"))
    assert os.path.exists(os.path.join(os.environ["LOCAL_UPLOAD_DIR"], ws, "bbbb2222.pdf"))

    assert client.delete(f"/workspaces/{ws}/papers/aaaa1111").status_code == 404


def test_delete_workspace_removes_everything_and_leaves_other_workspaces(client):
    ws1 = client.post("/workspaces", json={"name": "one"}).json()["workspace_id"]
    ws2 = client.post("/workspaces", json={"name": "two"}).json()["workspace_id"]
    _add_paper(ws1, "aaaa1111")
    _add_paper(ws1, "cccc3333")
    _add_paper(ws2, "bbbb2222")

    assert client.delete(f"/workspaces/{ws1}").status_code == 204

    assert client.get(f"/workspaces/{ws1}").status_code == 404
    assert [w["workspace_id"] for w in client.get("/workspaces").json()] == [ws2]
    assert _chunk_paper_ids() == ["bbbb2222"]
    assert not os.path.exists(os.path.join(os.environ["LOCAL_UPLOAD_DIR"], ws1))
    assert len(client.get(f"/workspaces/{ws2}/papers").json()) == 1


def test_cannot_delete_someone_elses_workspace_or_paper(client):
    ws = client.post("/workspaces", json={"name": "mine"}).json()["workspace_id"]
    _add_paper(ws, "aaaa1111")

    client.current["uid"] = OTHER_UID
    assert client.delete(f"/workspaces/{ws}/papers/aaaa1111").status_code == 403
    assert client.delete(f"/workspaces/{ws}").status_code == 403

    client.current["uid"] = UID
    assert len(client.get(f"/workspaces/{ws}/papers").json()) == 1


def test_search_with_empty_paper_scope_returns_nothing(client):
    from app.services import indexing
    ws = client.post("/workspaces", json={"name": "ws"}).json()["workspace_id"]
    _add_paper(ws, "aaaa1111")
    assert indexing.search_chunks("hello", [], top_k=5) == []
