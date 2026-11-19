"""
Redis caching -- strictly optional and fail-open: with no REDIS_URL (or Redis down)
every function behaves as a cache miss and the app works exactly as before.

Three layers:
  1. Exact answer cache     normalised question text      -> answer       (chat)
  2. Semantic answer cache  query-embedding cosine >= T   -> answer       (chat)
  3. Prompt cache           hash(task + system + user)    -> LLM output   (contradictions, gap analysis)

Correctness rule: a cached answer must never outlive the papers it was built from.
Every workspace has a corpus-version counter that is bumped on upload / delete / rename;
the version is part of every key, so old entries simply become unreachable (and expire by TTL).
Keys are also scoped by workspace and by the exact set of papers queried, so one user's cache
can never serve another workspace.
"""
from __future__ import annotations
import base64
import hashlib
import json
import re
import threading
import time
from collections import Counter

import numpy as np

from app.config import get_settings

_client = None
_down_until = 0.0
_lock = threading.Lock()
_stats: Counter = Counter()


# ---------------------------------------------------------------- connection
def use_client(client) -> None:
    """Injects a client (tests use fakeredis) and clears the outage flag."""
    global _client, _down_until
    _client, _down_until = client, 0.0


def reset() -> None:
    global _client, _down_until
    _client, _down_until = None, 0.0
    with _lock:
        _stats.clear()


def _get():
    global _client
    if time.time() < _down_until:
        return None
    if _client is None:
        url = get_settings().redis_url
        if not url:
            return None
        import redis
        _client = redis.Redis.from_url(url, socket_timeout=1.0, socket_connect_timeout=1.0, decode_responses=True)
    return _client


def _fail(exc: Exception) -> None:
    """Redis hiccup: count it and stop trying for 30s so requests don't each wait on a timeout."""
    global _down_until
    _down_until = time.time() + 30
    with _lock:
        _stats["errors"] += 1
    print(f"[cache] Redis unavailable, caching paused for 30s: {type(exc).__name__}: {exc}")


def enabled() -> bool:
    return _get() is not None


def stats() -> dict:
    with _lock:
        d = dict(_stats)
    d["enabled"] = enabled()
    return d


def _count(name: str) -> None:
    with _lock:
        _stats[name] += 1


# ---------------------------------------------------------------- keys / versions
def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower()).rstrip("?!. ")


def _h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def scope_hash(paper_ids: list[str]) -> str:
    return _h(",".join(sorted(paper_ids)))


def corpus_version(workspace_id: str) -> int:
    r = _get()
    if r is None:
        return 0
    try:
        return int(r.get(f"ws:{workspace_id}:ver") or 0)
    except Exception as e:
        _fail(e)
        return 0


def bump_corpus_version(workspace_id: str) -> None:
    """Call whenever a workspace's papers change (upload, delete, rename)."""
    r = _get()
    if r is None:
        return
    try:
        r.incr(f"ws:{workspace_id}:ver")
    except Exception as e:
        _fail(e)


def _scoped(kind: str, workspace_id: str, paper_ids: list[str]) -> str:
    return f"{kind}:{workspace_id}:{corpus_version(workspace_id)}:{scope_hash(paper_ids)}"


# ---------------------------------------------------------------- generic JSON values
def get_value(key: str):
    r = _get()
    if r is None:
        return None
    try:
        raw = r.get(key)
    except Exception as e:
        _fail(e)
        return None
    if raw is None:
        _count("miss")
        return None
    _count("hit_prompt" if key.startswith("llm:") else "hit_exact")
    return json.loads(raw)


def set_value(key: str, value, ttl: int | None = None) -> None:
    r = _get()
    if r is None:
        return
    try:
        r.set(key, json.dumps(value, default=str), ex=ttl or get_settings().cache_ttl_seconds)
    except Exception as e:
        _fail(e)


# ---------------------------------------------------------------- prompt cache
def prompt_key(task: str, system: str, user: str) -> str:
    return f"llm:{task}:{_h(system + chr(0) + user)}"


# ---------------------------------------------------------------- exact answer cache
def get_exact(kind: str, workspace_id: str, paper_ids: list[str], text: str):
    return get_value(f"ex:{_scoped(kind, workspace_id, paper_ids)}:{_h(normalize(text))}")


def set_exact(kind: str, workspace_id: str, paper_ids: list[str], text: str, value) -> None:
    set_value(f"ex:{_scoped(kind, workspace_id, paper_ids)}:{_h(normalize(text))}", value)


# ---------------------------------------------------------------- semantic answer cache
def _pack(vec) -> str:
    v = np.asarray(vec, dtype=np.float32)
    v = v / (np.linalg.norm(v) or 1.0)
    return base64.b64encode(v.astype(np.float16).tobytes()).decode("ascii")


def _unpack(b64: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(b64), dtype=np.float16).astype(np.float32)


def get_semantic(kind: str, workspace_id: str, paper_ids: list[str], embedding):
    """Returns (value, similarity) for the most similar cached query at/above the threshold, else None."""
    r = _get()
    if r is None:
        return None
    key = f"sem:{_scoped(kind, workspace_id, paper_ids)}"
    try:
        entries = r.lrange(key, 0, -1)
    except Exception as e:
        _fail(e)
        return None
    if not entries:
        _count("miss")
        return None
    q = np.asarray(embedding, dtype=np.float32)
    q = q / (np.linalg.norm(q) or 1.0)
    best, best_sim = None, -1.0
    for raw in entries:
        entry = json.loads(raw)
        e = _unpack(entry["e"])
        if e.shape != q.shape:
            continue
        sim = float(np.dot(q, e))
        if sim > best_sim:
            best, best_sim = entry["v"], sim
    if best is not None and best_sim >= get_settings().semantic_cache_threshold:
        _count("hit_semantic")
        return best, best_sim
    _count("miss")
    return None


def set_semantic(kind: str, workspace_id: str, paper_ids: list[str], embedding, value) -> None:
    r = _get()
    if r is None:
        return
    s = get_settings()
    key = f"sem:{_scoped(kind, workspace_id, paper_ids)}"
    try:
        pipe = r.pipeline()
        pipe.lpush(key, json.dumps({"e": _pack(embedding), "v": value}, default=str))
        pipe.ltrim(key, 0, s.semantic_cache_max_entries - 1)
        pipe.expire(key, s.cache_ttl_seconds)
        pipe.execute()
    except Exception as e:
        _fail(e)
