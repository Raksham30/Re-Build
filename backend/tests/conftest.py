import os
import pytest

# Tests fake embeddings as 3-dim vectors; the pgvector column must match.
os.environ["GEMINI_EMBEDDING_DIM"] = "3"


@pytest.fixture(autouse=True)
def _clean_postgres():
    """Each test starts from empty metadata tables (only when a test DB is configured)."""
    if not os.environ.get("DATABASE_URL"):
        yield
        return
    from app import db
    from app.config import get_settings
    get_settings.cache_clear()
    db.close_pool()
    with db.connection() as c:
        c.execute("TRUNCATE flags, extractions, papers, workspaces CASCADE")
    yield
    db.close_pool()
