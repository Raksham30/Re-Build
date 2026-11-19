"""
Metadata store for workspaces / papers / extractions / flags, on Postgres.

Same public function signatures as the old Cosmos/JSON implementation, so
nothing in api/ or agent.py changes. Deletes cascade in the schema
(workspace -> papers -> extractions, workspace -> flags); flags that merely
*involve* a paper are removed explicitly in delete_paper().
"""
from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone

from psycopg.types.json import Jsonb

from app.db import connection
from app.schemas import Workspace, Paper, StructuredExtraction


def _json_default(o):
    """Lets pydantic models (e.g. Citation objects inside flag payloads) be stored as JSON."""
    return o.model_dump() if hasattr(o, "model_dump") else str(o)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ws(row: dict) -> Workspace:
    return Workspace(
        workspace_id=row["workspace_id"],
        owner_uid=row["owner_uid"],
        name=row["name"],
        created_at=row["created_at"].isoformat(),
        updated_at=row["updated_at"].isoformat(),
    )


def _paper(row: dict) -> Paper:
    return Paper(
        paper_id=row["paper_id"],
        workspace_id=row["workspace_id"],
        filename=row["filename"],
        title=row["title"],
        num_pages=row["num_pages"],
        status=row["status"],
    )


# ==================== Workspaces ====================

def create_workspace(owner_uid: str, name: str) -> Workspace:
    with connection() as conn:
        row = conn.execute(
            "INSERT INTO workspaces (workspace_id, owner_uid, name) VALUES (%s, %s, %s) RETURNING *",
            (str(uuid.uuid4())[:8], owner_uid, name),
        ).fetchone()
    return _ws(row)


def rename_workspace(workspace_id: str, name: str) -> Workspace | None:
    with connection() as conn:
        row = conn.execute(
            "UPDATE workspaces SET name = %s, updated_at = now() WHERE workspace_id = %s RETURNING *",
            (name, workspace_id),
        ).fetchone()
    return _ws(row) if row else None


def list_workspaces(owner_uid: str) -> list[Workspace]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM workspaces WHERE owner_uid = %s ORDER BY created_at", (owner_uid,)
        ).fetchall()
    return [_ws(r) for r in rows]


def get_workspace(workspace_id: str) -> Workspace | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM workspaces WHERE workspace_id = %s", (workspace_id,)
        ).fetchone()
    return _ws(row) if row else None


def delete_workspace(workspace_id: str, owner_uid: str) -> None:
    """Deletes the workspace plus every paper, extraction and flag in it (FK cascade).
    Chunks in the search index and files in object storage are removed by the caller."""
    with connection() as conn:
        conn.execute(
            "DELETE FROM workspaces WHERE workspace_id = %s AND owner_uid = %s",
            (workspace_id, owner_uid),
        )


# ==================== Papers ====================

def save_paper(paper: Paper) -> None:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO papers (paper_id, workspace_id, filename, title, num_pages, status)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (paper_id) DO UPDATE SET
                filename = EXCLUDED.filename, title = EXCLUDED.title,
                num_pages = EXCLUDED.num_pages, status = EXCLUDED.status
            """,
            (paper.paper_id, paper.workspace_id, paper.filename, paper.title,
             paper.num_pages, paper.status),
        )


def rename_paper(workspace_id: str, paper_id: str, name: str) -> Paper | None:
    """Sets the display name (title) shown in the UI and in citations."""
    with connection() as conn:
        row = conn.execute(
            "UPDATE papers SET title = %s WHERE paper_id = %s AND workspace_id = %s RETURNING *",
            (name, paper_id, workspace_id),
        ).fetchone()
    return _paper(row) if row else None


def get_paper(workspace_id: str, paper_id: str) -> Paper | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM papers WHERE paper_id = %s AND workspace_id = %s",
            (paper_id, workspace_id),
        ).fetchone()
    return _paper(row) if row else None


def list_papers(workspace_id: str) -> list[Paper]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM papers WHERE workspace_id = %s ORDER BY created_at", (workspace_id,)
        ).fetchall()
    return [_paper(r) for r in rows]


def delete_paper(workspace_id: str, paper_id: str) -> None:
    """Deletes the paper (extraction cascades) and any flags that involve it."""
    with connection() as conn:
        conn.execute(
            "DELETE FROM flags WHERE workspace_id = %s AND %s = ANY (paper_ids_involved)",
            (workspace_id, paper_id),
        )
        conn.execute(
            "DELETE FROM papers WHERE paper_id = %s AND workspace_id = %s",
            (paper_id, workspace_id),
        )


# ==================== Extractions ====================

def save_extraction(workspace_id: str, paper_id: str, extraction: StructuredExtraction) -> None:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO extractions (paper_id, workspace_id, data) VALUES (%s, %s, %s)
            ON CONFLICT (paper_id) DO UPDATE SET data = EXCLUDED.data
            """,
            (paper_id, workspace_id, Jsonb(extraction.model_dump())),
        )


def _extraction(data: dict) -> StructuredExtraction:
    return StructuredExtraction(**{k: v for k, v in data.items() if k in StructuredExtraction.model_fields})


def get_extraction(workspace_id: str, paper_id: str) -> StructuredExtraction | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT data FROM extractions WHERE paper_id = %s AND workspace_id = %s",
            (paper_id, workspace_id),
        ).fetchone()
    return _extraction(row["data"]) if row else None


def get_extractions(workspace_id: str, paper_ids: list[str]) -> dict[str, StructuredExtraction]:
    if not paper_ids:
        return {}
    with connection() as conn:
        rows = conn.execute(
            "SELECT paper_id, data FROM extractions WHERE workspace_id = %s AND paper_id = ANY (%s)",
            (workspace_id, list(paper_ids)),
        ).fetchall()
    return {r["paper_id"]: _extraction(r["data"]) for r in rows}


# ==================== Flags (background gap/contradiction findings) ====================

_FLAG_COLUMNS = ("flag_id", "workspace_id", "status", "paper_ids_involved", "created_at")


def save_flag(workspace_id: str, flag: dict) -> None:
    # Flag payloads hold pydantic objects (Citation); normalise to plain JSON first.
    flag = json.loads(json.dumps(flag, default=_json_default))
    flag_id = flag.get("flag_id") or str(uuid.uuid4())[:8]
    status = flag.get("status", "new")
    created_at = flag.get("created_at") or _now_iso()
    papers = list(flag.get("paper_ids_involved") or [])
    data = {k: v for k, v in flag.items() if k not in _FLAG_COLUMNS}
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO flags (flag_id, workspace_id, status, paper_ids_involved, created_at, data)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (flag_id) DO UPDATE SET
                status = EXCLUDED.status, paper_ids_involved = EXCLUDED.paper_ids_involved,
                data = EXCLUDED.data
            """,
            (flag_id, workspace_id, status, papers, created_at, Jsonb(data)),
        )


def list_flags(workspace_id: str, include_dismissed: bool = False) -> list[dict]:
    sql = "SELECT * FROM flags WHERE workspace_id = %s"
    if not include_dismissed:
        sql += " AND status <> 'dismissed'"
    sql += " ORDER BY created_at"
    with connection() as conn:
        rows = conn.execute(sql, (workspace_id,)).fetchall()
    return [
        {
            **r["data"],
            "flag_id": r["flag_id"],
            "workspace_id": r["workspace_id"],
            "status": r["status"],
            "paper_ids_involved": r["paper_ids_involved"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def update_flag_status(workspace_id: str, flag_id: str, status: str) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE flags SET status = %s WHERE flag_id = %s AND workspace_id = %s",
            (status, flag_id, workspace_id),
        )


def _delete_flag(workspace_id: str, flag_id: str) -> None:
    with connection() as conn:
        conn.execute(
            "DELETE FROM flags WHERE flag_id = %s AND workspace_id = %s", (flag_id, workspace_id)
        )
