# Research Paper Assistant

A research workflow agent, not "chat with PDF": upload papers into a workspace, get
citation-grounded answers across your library, structured per-paper extraction
(datasets/methods/results/limitations), automatic background contradiction/gap detection
on every upload, and a research writer that drafts using your own ideas while citing real
uploaded papers.

## Stack

| Concern | Technology |
|---|---|
| API | FastAPI |
| Metadata, chunks, vectors, full-text | Postgres + pgvector |
| PDF files | S3-compatible storage (Cloudflare R2 / AWS S3 / MinIO); local disk in dev |
| PDF parsing | PyMuPDF (local, layout-aware, page-accurate) |
| Retrieval | Hybrid: pgvector dense + Postgres full-text, fused with RRF; section-aware chunking |
| Caching | Redis: exact + semantic answer cache, LLM prompt cache (optional, fail-open) |
| Embeddings / chat / extraction | Google Gemini, routed by task to light / standard / strong model tiers |
| End-user auth | Firebase (Google + email/password) |
| Frontend | React (Vite) in `frontend/` |

## Quickstart

```bash
cp backend/.env.example backend/.env      # set GEMINI_API_KEY
docker compose up --build                 # api + postgres(pgvector) + redis + minio
curl http://localhost:8010/health         # shows what is wired up
```

Without Docker: run any Postgres with the `vector` extension, set `DATABASE_URL`, then
`cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload --port 8010`.

Tests: `pip install -r backend/requirements-dev.txt`, set `DATABASE_URL` to a throwaway
database, `cd backend && pytest`. (`test_gemini_end_to_end.py` and `test_upload_pipeline.py`
are live tests that need a real `GEMINI_API_KEY`.)

## Features
- **Chat** with page-level citations, scoped to a workspace; cross-paper questions retrieve from every selected paper.
- **Structured extraction** per paper (datasets, methods, results, limitations).
- **Contradictions** between papers: on demand, and automatically on every upload (shown as findings).
- **Research gaps** across the library.
- **Review builder**: plan an outline (or give your own headings) → write grounded sections → regenerate any
  section with feedback → export markdown with a verified, renumbered reference list. Options: document type,
  organisation, length, tone, your own research, free-text instructions.



## Layout

```
backend/app/
  main.py, config.py, db.py (pool + schema), schemas.py, auth.py
  services/  parsing, chunking, embeddings, indexing (hybrid), extraction, generation, llm_router,
             cache (Redis), agent, review (review builder), storage (Postgres), file_storage (S3)
  api/       workspaces, papers, chat, research, flags
backend/eval/ retrieval benchmark (dense vs hybrid)
frontend/    React app (Vite): dashboard, workspace chat, gaps, contradictions, findings, review builder
docker-compose.yml
```
