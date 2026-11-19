from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.api import workspaces, papers, chat, research, flags
from app.config import get_settings
from app.services import cache, llm_router
from app.services.generation import LLMUnavailableError

app = FastAPI(title="Research Paper Assistant", version="0.3.0")

_settings = get_settings()
if _settings.is_production:
    # Fail closed: production must never run with dev-mode auth (bearer token == uid)
    # or a wildcard CORS policy.
    if not _settings.use_firebase:
        raise RuntimeError("APP_ENV=production requires FIREBASE_SERVICE_ACCOUNT_PATH (dev-mode auth is insecure).")
    if _settings.cors_origins.strip() in ("", "*"):
        raise RuntimeError("APP_ENV=production requires CORS_ORIGINS to list your frontend origin(s), not '*'.")

_origins = [o.strip() for o in _settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware, allow_origins=_origins or ["*"], allow_methods=["*"], allow_headers=["*"],
)

@app.exception_handler(LLMUnavailableError)
async def llm_unavailable_handler(_: Request, exc: LLMUnavailableError):
    # Quota/overload is an expected condition, not a server bug: return a
    # readable message the frontend can show instead of a 500 traceback.
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


app.include_router(workspaces.router)
app.include_router(papers.router)
app.include_router(chat.router)
app.include_router(research.router)
app.include_router(flags.router)


@app.get("/health")
def health():
    settings = get_settings()
    return {
        "status": "ok",
        "mode": {
            "auth": "firebase" if settings.use_firebase else "dev-mode (insecure, local only)",
            "metadata_db": "postgres" if settings.database_url else "NOT CONFIGURED (set DATABASE_URL)",
            "file_storage": "s3-compatible" if settings.use_s3 else "local-disk (dev only)",
            "pdf_parsing": "pymupdf",
            "embeddings": "gemini" if settings.use_gemini_embeddings else "NOT CONFIGURED (set GEMINI_API_KEY)",
            "chat_generation": "gemini" if settings.use_gemini_embeddings else "NOT CONFIGURED (set GEMINI_API_KEY)",
            "search_index": (f"pgvector (dim {settings.gemini_embedding_dim}, "
                             f"{'hybrid dense+keyword' if settings.hybrid_search else 'dense only'})"
                             if settings.database_url else "NOT CONFIGURED (set DATABASE_URL)"),
            "cache": "redis" if settings.use_redis else "disabled (set REDIS_URL)",
        },
        "usage": {"llm_calls_by_task_and_model": llm_router.usage_stats(), "cache": cache.stats()},
    }
