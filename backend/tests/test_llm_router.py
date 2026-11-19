"""Task -> tier -> model routing, plus fallback behaviour of run_gemini. No network."""
import pytest
from google.genai.errors import ClientError, ServerError

from app.config import get_settings
from app.services import generation, llm_router
from app.services.llm_router import Task


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in ("TASK_ROUTES", "GEMINI_LIGHT_MODELS", "GEMINI_STANDARD_MODELS", "GEMINI_STRONG_MODELS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GEMINI_LIGHT_MODELS", "l1,l2")
    monkeypatch.setenv("GEMINI_STANDARD_MODELS", "s1,l2")
    monkeypatch.setenv("GEMINI_STRONG_MODELS", "p1,s1")
    get_settings.cache_clear()
    llm_router.reset_stats()
    monkeypatch.setattr(generation.time, "sleep", lambda s: None)
    yield
    get_settings.cache_clear()


def test_default_task_tiers():
    assert llm_router.models_for(Task.EXTRACTION) == ["l1", "l2"]
    assert llm_router.models_for(Task.CONTRADICTION) == ["l1", "l2"]
    assert llm_router.models_for(Task.CHAT) == ["s1", "l2"]
    assert llm_router.models_for(Task.GAP_ANALYSIS) == ["s1", "l2"]
    assert llm_router.models_for(Task.WRITE) == ["p1", "s1"]


def test_task_routes_override(monkeypatch):
    monkeypatch.setenv("TASK_ROUTES", "write=light, chat=strong")
    get_settings.cache_clear()
    assert llm_router.models_for(Task.WRITE) == ["l1", "l2"]
    assert llm_router.models_for(Task.CHAT) == ["p1", "s1"]
    assert llm_router.models_for(Task.EXTRACTION) == ["l1", "l2"]   # untouched


def test_bad_task_routes_fails_loudly(monkeypatch):
    monkeypatch.setenv("TASK_ROUTES", "write=ultra")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="TASK_ROUTES"):
        llm_router.models_for(Task.WRITE)


def test_run_gemini_uses_task_primary_and_counts():
    seen = []
    assert generation.run_gemini(lambda m: seen.append(m) or "ok", task=Task.WRITE) == "ok"
    assert seen == ["p1"]
    assert llm_router.usage_stats() == {"write:p1": 1}


def test_daily_quota_falls_through_to_next_model_in_tier():
    seen = []

    def call(model):
        seen.append(model)
        if model == "p1":
            raise ClientError(429, {"error": {"message": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}})
        return "from-" + model

    assert generation.run_gemini(call, task=Task.WRITE) == "from-s1"
    assert seen == ["p1", "s1"]
    assert llm_router.usage_stats() == {"write:s1": 1}


def test_retired_model_404_is_skipped():
    def call(model):
        if model == "l1":
            raise ClientError(404, {"error": {"message": "model not found"}})
        return model

    assert generation.run_gemini(call, task=Task.EXTRACTION) == "l2"


def test_everything_exhausted_raises_clean_error():
    def call(model):
        raise ServerError(503, {"error": {"message": "overloaded"}})

    with pytest.raises(generation.LLMUnavailableError) as e:
        generation.run_gemini(call, task=Task.CHAT)
    assert e.value.status_code == 503
