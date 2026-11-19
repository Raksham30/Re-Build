"""
Central configuration (all from environment / .env).

Stack:
  * Postgres (+ pgvector)  -- metadata, chunks, vectors, full-text   (DATABASE_URL, required)
  * S3-compatible storage  -- uploaded PDFs: Cloudflare R2, AWS S3, MinIO.
                              If unset, PDFs stay on local disk (dev only).
  * Gemini                 -- embeddings, chat, extraction (GEMINI_API_KEY, required)
  * Firebase               -- end-user auth. If unset, dev mode (bearer token == uid).
"""
from __future__ import annotations
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
import os


class Settings(BaseSettings):
    # extra="ignore": an old .env that still holds AZURE_* / COSMOS_* keys must not crash startup.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Firebase Auth (end-user login only) ---
    firebase_service_account_path: str | None = None

    # --- Postgres ---
    database_url: str | None = None   # postgresql://user:pass@host:5432/dbname
    db_pool_max: int = 10

    # --- S3-compatible object storage (PDFs) ---
    s3_endpoint_url: str | None = None      # R2: https://<account>.r2.cloudflarestorage.com ; MinIO: http://minio:9000
    s3_bucket: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_region: str = "auto"                  # R2 uses "auto"; AWS needs the real region

    # --- Gemini (embeddings + chat + extraction) ---
    gemini_api_key: str | None = None
    gemini_embedding_model: str = "models/gemini-embedding-001"
    # Must match the pgvector column dimension (set at first schema creation).
    # pgvector's plain `vector` type supports up to 2000 dims; gemini-embedding-001
    # supports truncation to 768 / 1536 / 3072, so 1536 is the largest that fits.
    gemini_embedding_dim: int = 1536

    # Model routing (see services/llm_router.py). Each tier is a comma-separated,
    # ordered list: primary first, then fallbacks tried when a model is out of
    # quota / overloaded / retired. Free-tier quotas are per model.
    gemini_light_models: str = "gemini-flash-lite-latest,gemini-flash-latest"
    gemini_standard_models: str = "gemini-flash-latest,gemini-flash-lite-latest"
    gemini_strong_models: str = "gemini-pro-latest,gemini-flash-latest"
    thinking_headroom_tokens: int = 2048   # extra output budget so reasoning models don't truncate answers
    task_routes: str = ""   # optional overrides, e.g. "chat=light,write=standard"

    # --- Redis (optional): exact + semantic answer cache, LLM response cache ---
    redis_url: str | None = None             # redis://localhost:6379/0 ; blank = caching disabled
    cache_ttl_seconds: int = 24 * 3600
    semantic_cache_threshold: float = 0.93   # cosine similarity needed to reuse a cached answer
    semantic_cache_max_entries: int = 100    # per (workspace, paper-scope, corpus-version)

    # --- Retrieval ---
    hybrid_search: bool = True               # dense (pgvector) + keyword (Postgres FTS), fused with RRF

    # --- Deployment ---
    app_env: str = "development"             # "production" refuses to start without Firebase auth
    cors_origins: str = "*"                  # comma-separated origins, e.g. https://app.example.com

    # --- Local paths: parsing scratch space, and PDF storage when S3 is not configured ---
    local_data_dir: str = os.path.join(os.path.dirname(__file__), "..", "data")
    local_upload_dir: str = os.path.join(os.path.dirname(__file__), "..", "data", "uploads")

    @property
    def use_firebase(self) -> bool:
        return bool(self.firebase_service_account_path)

    @property
    def use_s3(self) -> bool:
        return bool(self.s3_bucket and self.s3_access_key_id and self.s3_secret_access_key)

    @property
    def use_redis(self) -> bool:
        return bool(self.redis_url)

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def use_gemini_embeddings(self) -> bool:
        return bool(self.gemini_api_key)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    os.makedirs(s.local_upload_dir, exist_ok=True)
    return s
