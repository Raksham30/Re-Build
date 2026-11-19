"""Whole pipeline on the new stack: PDF upload -> PyMuPDF parse -> chunk -> pgvector -> ask -> delete.
Only the Gemini calls are faked (embeddings, extraction, generation)."""
import os
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")


def _pdf_bytes():
    import pymupdf
    doc = pymupdf.open()
    for lines in (["Cats and Dogs", "Abstract", "We study cat behaviour.", "1 Introduction", "Cats are interesting."],
                  ["2 Results", "Cats beat dogs at napping.", "References", "[1] Someone."]):
        page = doc.new_page(); y = 100
        for l in lines:
            page.insert_text((72, y), l, fontsize=11); y += 16
    data = doc.tobytes(); doc.close()
    return data


@pytest.fixture()
def client(tmp_path, monkeypatch):
    for v in ("S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "FIREBASE_SERVICE_ACCOUNT_PATH"):
        monkeypatch.setenv(v, "")
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.setenv("LOCAL_UPLOAD_DIR", str(tmp_path / "up"))
    from app.config import get_settings
    get_settings.cache_clear()
    from app.schemas import StructuredExtraction
    from app.services import indexing, extraction, generation, agent
    monkeypatch.setattr(indexing, "embed_texts", lambda ts: [[1.0, 0.0, 0.0] if "cat" in t.lower() else [0.0, 1.0, 0.0] for t in ts])
    from app.api import papers
    monkeypatch.setattr(papers.extraction, "extract_structured_fields",
                        lambda pid, secs: StructuredExtraction(title="Cats and Dogs", methods=["observation"]))
    monkeypatch.setattr(generation, "generate", lambda system, user, max_tokens=600, task=None: "Cats nap more [Source 1].")
    monkeypatch.setattr(papers, "_run_background_flags", lambda *a, **k: None)
    from app.main import app
    from app.auth import get_current_uid
    app.dependency_overrides[get_current_uid] = lambda: "e2e-user"
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_upload_ask_delete(client):
    ws = client.post("/workspaces", json={"name": "e2e"}).json()["workspace_id"]
    r = client.post(f"/workspaces/{ws}/papers/upload", files={"file": ("cats.pdf", _pdf_bytes(), "application/pdf")})
    assert r.status_code == 200, r.text
    paper = r.json()
    assert paper["status"] == "indexed" and paper["num_pages"] == 2 and paper["title"] == "Cats and Dogs"

    ans = client.post(f"/workspaces/{ws}/chat/ask", json={"question": "what do cats do?"})
    assert ans.status_code == 200, ans.text
    body = ans.json()
    assert body["answer"].startswith("Cats nap")
    cits = body["citations"]
    assert cits and cits[0]["paper_title"] == "Cats and Dogs"
    assert "references" not in {c["section_type"] for c in cits[:1]}       # best hit is body text
    assert cits[0]["page_start"] in (1, 2)

    assert client.delete(f"/workspaces/{ws}/papers/{paper['paper_id']}").status_code in (200, 204)
    empty = client.post(f"/workspaces/{ws}/chat/ask", json={"question": "cats?"}).json()
    assert empty["citations"] == []
