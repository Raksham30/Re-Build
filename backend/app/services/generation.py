"""
Thin wrapper for "generate text from a prompt" used by the agent's
synthesis steps (answering, gap analysis, contradiction checks, writing).

Runs on Gemini exclusively; which model serves a call is decided by the
task router (services/llm_router.py). If GEMINI_API_KEY isn't set this
raises immediately rather than silently degrading.

Quota handling (shared with extraction.py via run_gemini):
  * per-minute 429  -> wait the delay Google asks for (short waits only)
  * per-DAY 429     -> retrying is pointless, move straight to the next
                       model in the tier's list (each model has its own
                       free-tier bucket)
  * everything exhausted -> LLMUnavailableError, which main.py turns into
                       a clean 429/503 instead of a 500 traceback.
"""
from __future__ import annotations
import re
import time
from typing import Callable, TypeVar

from app.config import get_settings
from app.services import cache
from app.services.llm_router import Task, models_for, record_call

T = TypeVar("T")

GEMINI_CHAT_MAX_RETRIES = 3       # attempts per model for transient errors
GEMINI_CHAT_BASE_BACKOFF = 2.0
GEMINI_MAX_WAIT_SECONDS = 20.0    # never block a request longer than this per wait


class LLMUnavailableError(RuntimeError):
    """Every configured Gemini model is rate-limited or overloaded."""

    def __init__(self, message: str, status_code: int = 429):
        super().__init__(message)
        self.status_code = status_code


# Tasks whose output is a pure function of the prompt (no user free-text drafting).
PROMPT_CACHED_TASKS = {Task.CONTRADICTION, Task.GAP_ANALYSIS}


def generate(system_prompt: str, user_prompt: str, max_tokens: int = 600,
             task: Task = Task.CHAT) -> str:
    key = None
    if task in PROMPT_CACHED_TASKS:
        # Identical prompt -> identical answer worth reusing. The prompt embeds the evidence,
        # so it changes (and misses) automatically whenever the underlying papers change.
        key = cache.prompt_key(task.value, system_prompt, user_prompt)
        hit = cache.get_value(key)
        if hit is not None:
            return hit
    out = _generate_gemini(system_prompt, user_prompt, max_tokens, task)
    if key:
        cache.set_value(key, out, ttl=7 * 24 * 3600)
    return out


def _is_daily_quota(err: Exception) -> bool:
    # Google names the violated quota, e.g. "...PerDayPerProjectPerModel-FreeTier".
    return "PerDay" in str(err)


def _suggested_delay(err: Exception) -> float | None:
    """Seconds Google asks us to wait ('retryDelay': '37s' / 'retry in 37.6s')."""
    m = re.search(r"retryDelay'?\"?:\s*'?\"?([\d.]+)s", str(err)) or \
        re.search(r"retry in ([\d.]+)s", str(err))
    return float(m.group(1)) if m else None


def run_gemini(call: Callable[[str], T], label: str = "Gemini", task: Task = Task.CHAT) -> T:
    """Runs call(model_name) with retry + model fallback, using the model list
    the router assigns to `task`. `call` must build and send one
    generate_content request for the given model."""
    from google.genai.errors import ClientError, ServerError

    settings = get_settings()
    last_err: Exception | None = None

    for model in models_for(task):
        for attempt in range(1, GEMINI_CHAT_MAX_RETRIES + 1):
            try:
                result = call(model)
                record_call(task, model)
                return result
            except (ClientError, ServerError) as e:
                code = getattr(e, "code", None)
                if code == 404:
                    # Fallback model name doesn't exist (renamed/retired) -- skip it.
                    print(f"[{label}] Model '{model}' not found; trying next model.")
                    last_err = e
                    break
                if code not in (429, 503):
                    raise  # bad request / bad key / etc. -- a real error
                last_err = e

                if code == 429 and _is_daily_quota(e):
                    print(f"[{label}] Daily quota exhausted for '{model}'; trying next model.")
                    break

                suggested = _suggested_delay(e) if code == 429 else None
                if suggested is not None and suggested > GEMINI_MAX_WAIT_SECONDS:
                    print(f"[{label}] '{model}' asks for a {suggested:.0f}s wait; trying next model.")
                    break
                if attempt == GEMINI_CHAT_MAX_RETRIES:
                    break

                wait = suggested if suggested is not None else GEMINI_CHAT_BASE_BACKOFF * (2 ** (attempt - 1))
                wait = min(wait + 0.5, GEMINI_MAX_WAIT_SECONDS)
                reason = "Rate limit" if code == 429 else "Model overloaded (503)"
                print(f"[{label}] {reason} on '{model}' (attempt {attempt}/{GEMINI_CHAT_MAX_RETRIES}). "
                      f"Retrying in {wait:.1f}s...")
                time.sleep(wait)

    code = getattr(last_err, "code", None)
    if code == 503:
        raise LLMUnavailableError(
            "The AI model is temporarily overloaded. Please try again in a minute.", 503
        ) from last_err
    raise LLMUnavailableError(
        "Gemini API quota exhausted for all configured models (free tier is limited per "
        "day). Try again later, enable billing on the Google AI Studio project, or add "
        "another model to the tier's GEMINI_*_MODELS list.", 429
    ) from last_err


def _generate_gemini(system_prompt: str, user_prompt: str, max_tokens: int, task: Task) -> str:
    settings = get_settings()
    if not settings.use_gemini_embeddings:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Chat generation runs on Gemini only "
            "(get a free key: https://aistudio.google.com/apikey)."
        )

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key)

    def _call(model: str) -> str:
        resp = client.models.generate_content(
            model=model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                # Thinking models spend part of this budget on hidden reasoning; without headroom a
                # long answer is silently cut short (or comes back empty).
                max_output_tokens=max_tokens + settings.thinking_headroom_tokens,
                temperature=0.2,
            ),
        )
        text = (resp.text or "").strip()
        if not text:
            raise LLMUnavailableError(f"{model} returned an empty response (token limit or safety filter).", 502)
        return text

    return run_gemini(_call, label=f"Gemini {task.value}", task=task)
