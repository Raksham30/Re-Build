"""Review builder: outline, grounded sections, citation validation, renumbering, API flow."""
import json
import os
import pytest
from fastapi.testclient import TestClient

from app.schemas import ReviewOptions, ReviewSection
from app.services import review

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")
UID = "review-user"


@pytest.fixture()
def env(monkeypatch):
    for v in ("S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "FIREBASE_SERVICE_ACCOUNT_PATH", "REDIS_URL"):
        monkeypatch.setenv(v, "")
    from app.config import get_settings
    get_settings.cache_clear()
    from app.schemas import Chunk, Paper, StructuredExtraction
    from app.services import generation, indexing, storage
    monkeypatch.setattr(indexing, "embed_texts", lambda ts: [[1.0, 0.0, 0.0] for _ in ts])

    ws = storage.create_workspace(UID, "w").workspace_id
    for pid, title, authors in (("pa", "Alpha Net", ["A. Smith"]), ("pb", "Beta Net", []), ("pc", "Gamma Net", ["C. Lee", "D. Kim"])):
        storage.save_paper(Paper(paper_id=pid, workspace_id=ws, filename=f"{pid}.pdf", title=title, status="indexed"))
        storage.save_extraction(ws, pid, StructuredExtraction(title=title, authors=authors, methods=[f"{title} method"]))
        indexing.index_chunks([Chunk(chunk_id=f"{pid}-1", paper_id=pid, text=f"{title} improves accuracy on benchmark",
                                     section_type="results", page_start=2, page_end=2, order=0)])
    storage.save_paper(Paper(paper_id="pu", workspace_id=ws, filename="u.pdf", status="failed"))   # not indexed: excluded

    calls = []
    def gen(system, user, max_tokens=600, task=None):
        calls.append((task.value, system, user, max_tokens))
        if task.value == "review_outline":
            return "```json\n" + json.dumps({"title": "Nets Review", "sections": [
                {"heading": "Intro", "goal": "motivate", "papers": [1, 2]},
                {"heading": "Compare", "goal": "compare", "papers": [3, 99]}]}) + "\n```"
        # section text: cites valid numbers, plus a hallucinated [9]
        return f"Alpha is strong [1]. Gamma agrees [3, 9]. Both beat Beta [2]."
    monkeypatch.setattr(generation, "generate", gen)
    from app.main import app
    from app.auth import get_current_uid
    app.dependency_overrides[get_current_uid] = lambda: UID
    yield TestClient(app), ws, calls
    app.dependency_overrides.clear(); get_settings.cache_clear()


def test_validate_citations_strips_unknown_numbers():
    text, warns = review.validate_citations("A [1]. B [2, 7]. C [8].", {1, 2})
    assert text == "A [1]. B [2]. C." and "7" in warns[0] and "8" in warns[0]


def test_outline_parses_json_and_maps_numbers_to_papers(env):
    client, ws, calls = env
    r = client.post(f"/workspaces/{ws}/research/review/outline", json={"options": {"topic": "nets"}})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["title"] == "Nets Review"
    assert out["sections"][0]["paper_ids"] == ["pa", "pb"]
    assert out["sections"][1]["paper_ids"] == ["pc"]               # 99 (unknown) dropped
    assert calls[0][0] == "review_outline"
    assert "Alpha Net" in calls[0][2] and "u.pdf" not in calls[0][2]   # un-indexed paper not offered


def test_custom_sections_skip_the_outline_call(env):
    client, ws, calls = env
    out = client.post(f"/workspaces/{ws}/research/review/outline",
                      json={"options": {"topic": "nets", "sections": ["Intro", " Methods ", ""]}}).json()
    assert [s["heading"] for s in out["sections"]] == ["Intro", "Methods"] and calls == []


def test_bad_outline_json_falls_back(env, monkeypatch):
    client, ws, _ = env
    from app.services import generation
    monkeypatch.setattr(generation, "generate", lambda *a, **k: "sorry, no JSON here")
    out = client.post(f"/workspaces/{ws}/research/review/outline", json={"options": {"topic": "nets", "own_research": "mine"}}).json()
    heads = [s["heading"] for s in out["sections"]]
    assert "Introduction" in heads and "Positioning of the Proposed Work" in heads


def test_section_is_grounded_validated_and_uses_strong_tier(env):
    client, ws, calls = env
    r = client.post(f"/workspaces/{ws}/research/review/section", json={
        "options": {"topic": "nets", "length": "short", "tone": "concise", "own_research": "We built Delta."},
        "section": {"heading": "Compare", "goal": "compare", "paper_ids": ["pa", "pc"]},
        "previous_headings": ["Intro"]}).json()
    task, system, user, max_tokens = calls[-1]
    assert task == "review_section"
    assert "[1] \"Alpha Net\"" in user and "[3] \"Gamma Net\"" in user and "Beta Net\"" not in user   # only scoped papers
    assert "excerpt (results" in user and "AUTHOR'S OWN RESEARCH:\nWe built Delta." in user
    assert "Intro" in user and "about 150 words" in system
    assert "[9]" not in r["content"] and "[3]" in r["content"]         # hallucinated 9 stripped
    assert "[2]" not in r["content"]                                   # Beta was out of scope for this section
    assert r["content"] == "Alpha is strong [1]. Gamma agrees [3]. Both beat Beta."
    assert any("2" in w and "9" in w for w in r["warnings"])


def test_assemble_renumbers_by_first_appearance_and_builds_references(env):
    client, ws, _ = env
    secs = [{"heading": "A", "content": "x [3]. y [1, 3]."}, {"heading": "B", "content": "z [3] and [2]."}]
    d = client.post(f"/workspaces/{ws}/research/review/assemble",
                    json={"options": {"topic": "nets"}, "title": "T", "sections": secs}).json()
    # first appearance order: 3 -> 1, 1 -> 2, 2 -> 3
    assert [s["content"] for s in d["sections"]] == ["x [1]. y [1, 2].", "z [1] and [3]."]
    assert [(r["number"], r["title"]) for r in d["references"]] == [(1, "Gamma Net"), (2, "Alpha Net"), (3, "Beta Net")]
    assert d["references"][0]["formatted"] == '[1] C. Lee, D. Kim. "Gamma Net."'
    assert d["references"][2]["formatted"] == '[3] "Beta Net."'                     # no authors known
    assert d["markdown"].startswith("# T\n\n## A\n\nx [1]. y [1, 2].") and "## References" in d["markdown"]
    assert d["warnings"] == []


def test_assemble_warns_about_uncited_selected_papers(env):
    client, ws, _ = env
    d = client.post(f"/workspaces/{ws}/research/review/assemble",
                    json={"options": {"topic": "nets"}, "title": "T",
                          "sections": [{"heading": "A", "content": "only [1]."}]}).json()
    assert len(d["references"]) == 1 and "Beta Net" in d["warnings"][0] and "Gamma Net" in d["warnings"][0]


def test_full_review_one_shot(env):
    client, ws, calls = env
    d = client.post(f"/workspaces/{ws}/research/review", json={"options": {"topic": "nets", "paper_ids": ["pa", "pb", "pc"]}})
    assert d.status_code == 200, d.text
    d = d.json()
    assert d["title"] == "Nets Review" and [s["heading"] for s in d["sections"]] == ["Intro", "Compare"]
    tasks = sorted(c[0] for c in calls)
    assert tasks == ["review_outline", "review_section", "review_section"]
    assert all(r["number"] >= 1 for r in d["references"]) and d["markdown"].count("## ") >= 3
    assert [s["heading"] for s in d["raw_sections"]] == ["Intro", "Compare"]      # stable numbering kept for regeneration
    assert "[3]" in d["raw_sections"][1]["content"]


def test_user_supplied_outline_skips_outline_call(env):
    client, ws, calls = env
    outline = {"title": "Mine", "sections": [{"heading": "Only", "goal": "", "paper_ids": []}]}
    d = client.post(f"/workspaces/{ws}/research/review", json={"options": {"topic": "nets"}, "outline": outline}).json()
    assert d["title"] == "Mine" and [c[0] for c in calls] == ["review_section"]


def test_revision_with_feedback_includes_previous_text(env):
    client, ws, calls = env
    client.post(f"/workspaces/{ws}/research/review/section", json={
        "options": {"topic": "nets"}, "section": {"heading": "Intro"},
        "previous_text": "OLD DRAFT TEXT [1].", "feedback": "make it shorter"})
    user = calls[-1][2]
    assert "OLD DRAFT TEXT" in user and "make it shorter" in user


def test_length_changes_budget_and_target(env):
    client, ws, calls = env
    for length in ("short", "long"):
        client.post(f"/workspaces/{ws}/research/review/section",
                    json={"options": {"topic": "n", "length": length}, "section": {"heading": "H"}})
    assert calls[-2][3] < calls[-1][3] and "about 500 words" in calls[-1][1]


def test_no_indexed_papers_gives_400_not_500(env):
    client, ws, _ = env
    from app.services import storage
    empty = storage.create_workspace(UID, "empty").workspace_id
    r = client.post(f"/workspaces/{empty}/research/review", json={"options": {"topic": "x"}})
    assert r.status_code == 400 and "indexed" in r.json()["detail"]
    r = client.post(f"/workspaces/{ws}/research/review/section",
                    json={"options": {"topic": "x", "paper_ids": ["pu"]}, "section": {"heading": "H"}})
    assert r.status_code == 400                                         # failed (unindexed) paper alone isn't usable


def test_other_users_workspace_is_forbidden(env):
    client, ws, _ = env
    from app.main import app
    from app.auth import get_current_uid
    app.dependency_overrides[get_current_uid] = lambda: "intruder"
    r = client.post(f"/workspaces/{ws}/research/review", json={"options": {"topic": "x"}})
    assert r.status_code in (403, 404)


def test_eval_script_reports_dense_and_hybrid(env):
    import tempfile, json as _json
    from eval.retrieval_eval import evaluate
    client, ws, _ = env
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write(_json.dumps({"question": "alpha accuracy", "expect": ["Alpha Net improves"]}) + "\n")
    out = evaluate(ws, f.name)
    assert set(out) == {"dense", "hybrid"} and out["hybrid"]["hit@8"] == 1.0 and out["hybrid"]["n"] == 1
