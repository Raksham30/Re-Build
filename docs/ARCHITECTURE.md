# Architecture

```
React (Vite) ──Firebase ID token──▶ FastAPI ─┬─▶ Postgres + pgvector   metadata, chunks, vectors, full-text
                                             ├─▶ S3-compatible store   original PDFs (R2 / S3 / MinIO)
                                             ├─▶ Redis (optional)      answer cache, prompt cache
                                             └─▶ Gemini                embeddings + generation (task-routed)
```

## Upload pipeline (`api/papers.py`)
1. Validate (PDF, ≤ 20 MB, streamed) → store the file (S3 or local disk) → paper row `parsing`.
2. **Parse** with PyMuPDF (`services/parsing.py`): reading order, running headers/footers removed, headings
   detected → sections with exact page ranges.
3. In parallel:
   - **Chunk + index** (`chunking.py`, `indexing.py`): section-bounded, sentence-aware chunks (references skipped);
     each chunk is embedded with a `Paper title – Section` header and stored with a generated `tsvector`.
   - **Extract** (`extraction.py`): structured datasets / methods / results / limitations (light-tier model).
4. Paper → `indexed`; the workspace **corpus version** is bumped (invalidates cached answers); a background task
   checks the new paper against existing ones for contradictions and stores **flags**.

## Retrieval (`services/indexing.py`)
Hybrid: pgvector cosine (meaning) + Postgres full-text `ts_rank_cd` (exact terms, acronyms, numbers), fused with
Reciprocal Rank Fusion. Multi-paper questions retrieve per paper so every selected paper is represented.
`eval/retrieval_eval.py` measures dense vs hybrid on your own questions.

## Model routing (`services/llm_router.py`)
| Tier | Tasks |
|---|---|
| light | extraction, contradiction checks |
| standard | chat answers, gap analysis, review outlines |
| strong | research drafting, review sections |

Each tier is an ordered model list with automatic fallback on quota / overload / retired models.
`TASK_ROUTES` overrides the task→tier map without code changes. `/health` shows calls per task and model.

## Caching (`services/cache.py`)
Fail-open: no Redis ⇒ everything still works. Chat answers: exact (normalised text) then semantic (cosine ≥ 0.93).
Contradiction and gap-analysis LLM calls: prompt-hash cache. Keys include workspace, paper set and corpus
version, so a stale answer can never survive an upload, delete or rename.

## Review builder (`services/review.py`)
outline (editable) → per-section writing from retrieved excerpts (strong tier) → citation validation (unknown
`[n]` stripped) → assemble (renumber by first appearance, reference list, markdown). Sections can be regenerated
with feedback and re-assembled without calling the model again.

## Auth & deployment
Firebase ID tokens verified with the Admin SDK. `APP_ENV=production` refuses to start without Firebase
credentials or with wildcard CORS. Schema is created idempotently at first connect; the embedding dimension is
fixed at table creation and checked on every start.
