"""
Model routing: every LLM call declares a Task; the router maps the task to a
cost tier and the tier to an ordered list of models (primary first, then
fallbacks used when a model is out of quota / overloaded / retired).

  light     cheap + fast   -> extraction, contradiction checks
  standard  balanced       -> RAG chat answers, gap analysis, review outlines
  strong    best quality   -> research drafting, review sections

Tier -> models comes from settings (GEMINI_{LIGHT,STANDARD,STRONG}_MODELS).
Task -> tier can be overridden per deployment with TASK_ROUTES, e.g.
TASK_ROUTES="chat=light,write=standard" (handy for cutting cost or testing).
"""
from __future__ import annotations
import threading
from collections import Counter
from enum import Enum

from app.config import get_settings


class Task(str, Enum):
    EXTRACTION = "extraction"
    CONTRADICTION = "contradiction"
    CHAT = "chat"
    GAP_ANALYSIS = "gap_analysis"
    WRITE = "write"                  # free-form research drafting
    REVIEW_OUTLINE = "review_outline"
    REVIEW_SECTION = "review_section"


class Tier(str, Enum):
    LIGHT = "light"
    STANDARD = "standard"
    STRONG = "strong"


DEFAULT_TASK_TIERS: dict[Task, Tier] = {
    Task.EXTRACTION: Tier.LIGHT,
    Task.CONTRADICTION: Tier.LIGHT,
    Task.CHAT: Tier.STANDARD,
    Task.GAP_ANALYSIS: Tier.STANDARD,
    Task.WRITE: Tier.STRONG,
    Task.REVIEW_OUTLINE: Tier.STANDARD,
    Task.REVIEW_SECTION: Tier.STRONG,
}


def _split(csv: str) -> list[str]:
    return list(dict.fromkeys(m.strip() for m in csv.split(",") if m.strip()))


def _parse_overrides(raw: str) -> dict[Task, Tier]:
    out: dict[Task, Tier] = {}
    for part in _split(raw):
        task_s, _, tier_s = part.partition("=")
        try:
            out[Task(task_s.strip())] = Tier(tier_s.strip())
        except ValueError:
            raise ValueError(
                f"Bad TASK_ROUTES entry '{part}'. Use task=tier with task in "
                f"{[t.value for t in Task]} and tier in {[t.value for t in Tier]}."
            ) from None
    return out


def tier_for(task: Task) -> Tier:
    overrides = _parse_overrides(get_settings().task_routes)
    return overrides.get(task, DEFAULT_TASK_TIERS[task])


def models_for(task: Task) -> list[str]:
    s = get_settings()
    csv = {Tier.LIGHT: s.gemini_light_models,
           Tier.STANDARD: s.gemini_standard_models,
           Tier.STRONG: s.gemini_strong_models}[tier_for(task)]
    models = _split(csv)
    if not models:
        raise RuntimeError(f"No models configured for tier '{tier_for(task).value}'.")
    return models


# ---- lightweight usage counters (which model actually served which task) ----
_stats: Counter = Counter()
_stats_lock = threading.Lock()


def record_call(task: Task, model: str) -> None:
    with _stats_lock:
        _stats[(task.value, model)] += 1


def usage_stats() -> dict[str, int]:
    with _stats_lock:
        return {f"{t}:{m}": n for (t, m), n in sorted(_stats.items())}


def reset_stats() -> None:
    with _stats_lock:
        _stats.clear()
