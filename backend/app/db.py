"""
Postgres connection pool + schema bootstrap.

One pool per process (psycopg3). The schema is created idempotently on
first use, guarded by an advisory lock so several workers starting at once
don't race. Rows come back as dicts.

Tables: workspaces / papers / extractions / flags (metadata) and chunks
(text + pgvector embedding + generated tsvector for full-text search).
The embedding dimension is fixed when the chunks table is first created
(GEMINI_EMBEDDING_DIM); changing it later needs a reindex, so a mismatch
raises a clear error instead of silently corrupting search.
"""
from __future__ import annotations
import threading
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import get_settings

_pool: ConnectionPool | None = None
_lock = threading.Lock()

_SCHEMA_LOCK_KEY = 727274  # arbitrary constant shared by all workers

def build_schema(dim: int) -> str:
    return f"""
SELECT pg_advisory_xact_lock({_SCHEMA_LOCK_KEY});
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS workspaces (
    workspace_id TEXT PRIMARY KEY,
    owner_uid    TEXT NOT NULL,
    name         TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_workspaces_owner ON workspaces (owner_uid);

CREATE TABLE IF NOT EXISTS papers (
    paper_id     TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces (workspace_id) ON DELETE CASCADE,
    filename     TEXT NOT NULL,
    title        TEXT NOT NULL DEFAULT '',
    num_pages    INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'uploaded',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_papers_workspace ON papers (workspace_id, created_at);

CREATE TABLE IF NOT EXISTS extractions (
    paper_id     TEXT PRIMARY KEY REFERENCES papers (paper_id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL,
    data         JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_extractions_workspace ON extractions (workspace_id);

CREATE TABLE IF NOT EXISTS flags (
    flag_id            TEXT PRIMARY KEY,
    workspace_id       TEXT NOT NULL REFERENCES workspaces (workspace_id) ON DELETE CASCADE,
    status             TEXT NOT NULL DEFAULT 'new',
    paper_ids_involved TEXT[] NOT NULL DEFAULT '{{}}',
    created_at         TEXT NOT NULL,
    data               JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_flags_workspace ON flags (workspace_id);
CREATE INDEX IF NOT EXISTS idx_flags_papers ON flags USING GIN (paper_ids_involved);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id     TEXT PRIMARY KEY,
    paper_id     TEXT NOT NULL REFERENCES papers (paper_id) ON DELETE CASCADE,
    text         TEXT NOT NULL,
    section_type TEXT NOT NULL,
    page_start   INTEGER NOT NULL,
    page_end     INTEGER NOT NULL,
    chunk_order  INTEGER NOT NULL DEFAULT 0,
    embedding    vector({dim}) NOT NULL,
    tsv          tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
);
CREATE INDEX IF NOT EXISTS idx_chunks_paper ON chunks (paper_id, chunk_order);
CREATE INDEX IF NOT EXISTS idx_chunks_tsv ON chunks USING GIN (tsv);
"""

# NOTE: no ANN (HNSW/IVF) index on chunks.embedding on purpose. Every query is
# scoped to a handful of papers via paper_id, so an exact scan over the few
# thousand matching rows is fast AND exact; an ANN index would post-filter by
# paper_id and can silently return fewer than top_k rows. Add HNSW when a
# single scope grows into the hundreds of thousands of chunks.


def _check_embedding_dim(conn, expected: int) -> None:
    row = conn.execute(
        "SELECT atttypmod AS dim FROM pg_attribute "
        "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
    ).fetchone()
    if row and row["dim"] != expected:
        raise RuntimeError(
            f"chunks.embedding is vector({row['dim']}) but GEMINI_EMBEDDING_DIM={expected}. "
            "Re-create the chunks table (DROP TABLE chunks) and re-upload / reindex papers, "
            "or set GEMINI_EMBEDDING_DIM back to match."
        )


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        with _lock:
            if _pool is None:
                settings = get_settings()
                if not settings.database_url:
                    raise RuntimeError(
                        "DATABASE_URL is not set. Point it at a Postgres instance, e.g. "
                        "postgresql://user:pass@localhost:5432/research"
                    )
                pool = ConnectionPool(
                    settings.database_url,
                    min_size=1,
                    max_size=settings.db_pool_max,
                    kwargs={"row_factory": dict_row},
                    open=True,
                )
                dim = settings.gemini_embedding_dim
                with pool.connection() as conn:
                    conn.execute(build_schema(dim))
                    _check_embedding_dim(conn, dim)
                _pool = pool
    return _pool


@contextmanager
def connection():
    """Yields a pooled connection; commits on clean exit, rolls back on error."""
    with get_pool().connection() as conn:
        yield conn


def close_pool() -> None:
    global _pool
    with _lock:
        if _pool is not None:
            _pool.close()
            _pool = None
