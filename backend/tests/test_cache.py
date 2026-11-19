"""Redis cache layers on fakeredis: exact, semantic, prompt cache, version invalidation, fail-open."""
import fakeredis
import pytest

from app.config import get_settings
from app.services import cache


@pytest.fixture(autouse=True)
def redis(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://fake")
    get_settings.cache_clear()
    cache.reset()
    client = fakeredis.FakeRedis(decode_responses=True)
    cache.use_client(client)
    yield client
    cache.reset()
    get_settings.cache_clear()


def test_exact_roundtrip_is_normalised_and_scoped():
    cache.set_exact("chat", "w1", ["p1", "p2"], "  What is X?? ", {"a": 1})
    assert cache.get_exact("chat", "w1", ["p2", "p1"], "what is x") == {"a": 1}       # order/case/punct insensitive
    assert cache.get_exact("chat", "w2", ["p1", "p2"], "what is x") is None           # other workspace
    assert cache.get_exact("chat", "w1", ["p1"], "what is x") is None                 # other paper scope


def test_corpus_version_bump_invalidates_everything_in_workspace():
    cache.set_exact("chat", "w1", ["p1"], "q", {"a": 1})
    cache.set_semantic("chat", "w1", ["p1"], [1.0, 0.0, 0.0], {"a": 1})
    cache.bump_corpus_version("w1")
    assert cache.get_exact("chat", "w1", ["p1"], "q") is None
    assert cache.get_semantic("chat", "w1", ["p1"], [1.0, 0.0, 0.0]) is None
    cache.set_exact("chat", "w2", ["p1"], "q", {"b": 2})
    cache.bump_corpus_version("w1")
    assert cache.get_exact("chat", "w2", ["p1"], "q") == {"b": 2}                    # other workspace untouched


def test_semantic_hit_above_threshold_only():
    cache.set_semantic("chat", "w1", ["p1"], [1.0, 0.0, 0.0], {"ans": "cats"})
    hit = cache.get_semantic("chat", "w1", ["p1"], [0.99, 0.05, 0.0])
    assert hit and hit[0] == {"ans": "cats"} and hit[1] > 0.99
    assert cache.get_semantic("chat", "w1", ["p1"], [0.6, 0.8, 0.0]) is None          # cosine 0.6 < 0.93
    assert cache.get_semantic("chat", "w9", ["p1"], [1.0, 0.0, 0.0]) is None


def test_semantic_cache_is_capped(monkeypatch):
    monkeypatch.setenv("SEMANTIC_CACHE_MAX_ENTRIES", "3")
    get_settings.cache_clear()
    for i in range(6):
        cache.set_semantic("chat", "w1", ["p1"], [1.0, float(i), 0.0], {"i": i})
    key = next(k for k in cache._get().keys("sem:*"))
    assert cache._get().llen(key) == 3


def test_prompt_cache_key_depends_on_all_parts():
    k1 = cache.prompt_key("contradiction", "sys", "user")
    assert k1 == cache.prompt_key("contradiction", "sys", "user")
    assert k1 != cache.prompt_key("contradiction", "sys", "user2")
    assert k1 != cache.prompt_key("gap_analysis", "sys", "user")
    cache.set_value(k1, "NONE")
    assert cache.get_value(k1) == "NONE"


def test_stats_counts_hits_and_misses():
    cache.get_exact("chat", "w1", ["p1"], "q")                    # miss
    cache.set_exact("chat", "w1", ["p1"], "q", 1)
    cache.get_exact("chat", "w1", ["p1"], "q")                    # hit
    s = cache.stats()
    assert s["miss"] == 1 and s["hit_exact"] == 1 and s["enabled"] is True


def test_fails_open_when_redis_errors():
    class Broken:
        def __getattr__(self, name):
            def boom(*a, **k):
                raise ConnectionError("down")
            return boom
    cache.use_client(Broken())
    cache.set_exact("chat", "w1", ["p1"], "q", 1)                 # must not raise
    assert cache.get_exact("chat", "w1", ["p1"], "q") is None
    assert cache.stats()["errors"] >= 1
    assert cache.enabled() is False                               # paused after the outage


def test_disabled_without_redis_url(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "")
    get_settings.cache_clear()
    cache.reset()
    assert cache.enabled() is False
    assert cache.get_exact("chat", "w", ["p"], "q") is None
    cache.set_exact("chat", "w", ["p"], "q", 1)                   # silently ignored
