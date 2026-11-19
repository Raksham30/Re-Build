"""
Concurrent upload pipeline: verify that a failure in the extraction branch
surfaces correctly as an HTTP 500, even when the chunking+indexing branch
succeeds. This is the 'less obvious of the two failure orders' the user
specifically asked to see tested.
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

UID = "concurrent_test_user"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Force S3/Firebase off (local disk + dev auth)
    for var in (
        "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_ENDPOINT_URL",
        "FIREBASE_SERVICE_ACCOUNT_PATH",
    ):
        monkeypatch.setenv(var, "")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LOCAL_UPLOAD_DIR", str(tmp_path / "uploads"))

    from app.config import get_settings
    get_settings.cache_clear()

    # Fake embeddings so indexing works without Gemini
    from app.services import indexing
    monkeypatch.setattr(indexing, "embed_texts", lambda texts: [[1.0, 0.0, 0.0] for _ in texts])

    from app.main import app
    from app.auth import get_current_uid
    app.dependency_overrides[get_current_uid] = lambda: UID
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _make_minimal_pdf():
    """A small valid PDF with a text layer (1 page)."""
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Abstract", fontsize=12)
    page.insert_text((72, 120), "Some real text so the parser finds content.", fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def test_extraction_failure_surfaces_as_500_when_chunking_succeeds(client, monkeypatch):
    """
    The concurrent pipeline calls:
        chunks_result = future_chunks.result()   # succeeds
        fields = future_fields.result()          # raises RuntimeError

    This test proves that even though future_chunks.result() returns
    normally, the subsequent future_fields.result() raising an exception
    is NOT swallowed -- it propagates as an HTTP 500 to the client.
    """
    from app.services import extraction

    # Make extraction blow up with a distinctive error
    def _boom_extraction(paper_id, sections):
        raise RuntimeError("DELIBERATE EXTRACTION FAILURE FOR TEST")

    monkeypatch.setattr(extraction, "extract_structured_fields", _boom_extraction)

    # Create a workspace first
    ws = client.post("/workspaces", json={"name": "extraction-fail-test"}).json()
    ws_id = ws["workspace_id"]

    # Upload a minimal PDF -- chunking+indexing should succeed,
    # but extraction should fail
    pdf_bytes = _make_minimal_pdf()
    resp = client.post(
        f"/workspaces/{ws_id}/papers/upload",
        files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
    )

    # The response MUST be 500, not 200
    assert resp.status_code == 500, (
        f"Expected HTTP 500 when extraction fails, got {resp.status_code}: {resp.text}"
    )
    detail = resp.json()["detail"]
    assert "DELIBERATE EXTRACTION FAILURE FOR TEST" in detail, (
        f"Expected the extraction error message in the response, got: {detail}"
    )
    print(f"[TEST PASSED] Extraction failure surfaced as HTTP 500: {detail}")


def test_chunking_failure_surfaces_as_500_when_extraction_would_succeed(client, monkeypatch):
    """Complementary test: if chunking/indexing fails, that also surfaces as 500."""
    from app.services import chunking, extraction

    def _boom_chunking(paper_id, sections):
        raise RuntimeError("DELIBERATE CHUNKING FAILURE FOR TEST")

    # extraction returns normally
    from app.schemas import StructuredExtraction
    monkeypatch.setattr(chunking, "chunk_sections", _boom_chunking)
    monkeypatch.setattr(extraction, "extract_structured_fields",
                        lambda pid, secs: StructuredExtraction(title="ok"))

    ws = client.post("/workspaces", json={"name": "chunking-fail-test"}).json()
    ws_id = ws["workspace_id"]

    pdf_bytes = _make_minimal_pdf()
    resp = client.post(
        f"/workspaces/{ws_id}/papers/upload",
        files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
    )

    assert resp.status_code == 500, (
        f"Expected HTTP 500 when chunking fails, got {resp.status_code}: {resp.text}"
    )
    detail = resp.json()["detail"]
    assert "DELIBERATE CHUNKING FAILURE FOR TEST" in detail, (
        f"Expected the chunking error message in the response, got: {detail}"
    )
    print(f"[TEST PASSED] Chunking failure surfaced as HTTP 500: {detail}")
