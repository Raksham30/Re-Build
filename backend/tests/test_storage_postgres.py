"""Storage contract tests against a real Postgres. Set DATABASE_URL to run."""
import os
import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")


@pytest.fixture()
def st():
    from app import db
    from app.config import get_settings
    get_settings.cache_clear()
    db.close_pool()
    from app.services import storage
    with db.connection() as c:
        c.execute("TRUNCATE flags, extractions, papers, workspaces CASCADE")
    yield storage
    db.close_pool()


def _paper(ws, pid, **kw):
    from app.schemas import Paper
    return Paper(paper_id=pid, workspace_id=ws, filename=f"{pid}.pdf", **kw)


def test_workspace_crud_and_ownership(st):
    ws = st.create_workspace("alice", "W1")
    assert st.get_workspace(ws.workspace_id).name == "W1"
    assert [w.workspace_id for w in st.list_workspaces("alice")] == [ws.workspace_id]
    assert st.list_workspaces("bob") == []
    assert st.rename_workspace(ws.workspace_id, "W2").name == "W2"
    st.delete_workspace(ws.workspace_id, "bob")          # wrong owner: no-op
    assert st.get_workspace(ws.workspace_id) is not None
    st.delete_workspace(ws.workspace_id, "alice")
    assert st.get_workspace(ws.workspace_id) is None


def test_papers_extractions_flags_and_cascade(st):
    from app.schemas import StructuredExtraction
    ws = st.create_workspace("alice", "W").workspace_id
    st.save_paper(_paper(ws, "p1", title="One", status="indexed"))
    st.save_paper(_paper(ws, "p2"))
    st.save_paper(_paper(ws, "p1", title="One", status="indexed", num_pages=7))  # upsert
    assert [p.paper_id for p in st.list_papers(ws)] == ["p1", "p2"]
    assert st.get_paper(ws, "p1").num_pages == 7
    assert st.get_paper("other-ws", "p1") is None
    assert st.rename_paper(ws, "p2", "Two").title == "Two"

    st.save_extraction(ws, "p1", StructuredExtraction(title="One", methods=["m"]))
    st.save_extraction(ws, "p2", StructuredExtraction(title="Two"))
    assert st.get_extraction(ws, "p1").methods == ["m"]
    assert set(st.get_extractions(ws, ["p1", "p2", "nope"])) == {"p1", "p2"}

    st.save_flag(ws, {"type": "gap", "paper_ids_involved": ["p1", "p2"], "payload": {"x": 1}})
    st.save_flag(ws, {"type": "gap", "paper_ids_involved": ["p2"], "payload": {}})
    flags = st.list_flags(ws)
    assert len(flags) == 2 and flags[0]["status"] == "new" and flags[0]["payload"] == {"x": 1}
    st.update_flag_status(ws, flags[1]["flag_id"], "dismissed")
    assert len(st.list_flags(ws)) == 1
    assert len(st.list_flags(ws, include_dismissed=True)) == 2

    st.delete_paper(ws, "p1")
    assert st.get_paper(ws, "p1") is None and st.get_extraction(ws, "p1") is None
    assert [f["paper_ids_involved"] for f in st.list_flags(ws, include_dismissed=True)] == [["p2"]]

    st.delete_workspace(ws, "alice")
    assert st.list_papers(ws) == [] and st.list_flags(ws, include_dismissed=True) == []


def test_flag_payload_accepts_pydantic_objects(st):
    from app.schemas import Citation
    ws = st.create_workspace("alice", "W").workspace_id
    cit = Citation(paper_id="p", paper_title="T", section_type="results", page_start=1, page_end=1, snippet="s")
    st.save_flag(ws, {"type": "contradiction", "paper_ids_involved": ["p"], "payload": {"c": cit}})
    assert st.list_flags(ws)[0]["payload"]["c"]["snippet"] == "s"
