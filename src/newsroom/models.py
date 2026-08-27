"""Model tiers, mapped to the agent hierarchy.

Two backends, selected by ``[models] backend`` in config.toml:

  backend = "ollama"      three local models, one per tier. $0.00, no key, but
                          spends the wall-clock and RAM that budget.py meters.
  backend = "openrouter"  the same three tiers served by OpenRouter's OpenAI-
                          compatible API. This is what lets the pipeline run in
                          CI — GitHub Actions has no GPU to host Ollama — so the
                          weekly edition can regenerate itself unattended. The
                          key is read from $OPENROUTER_API_KEY and never stored.

Nothing about the tiers above this file changes with the backend: the graph, the
agents and the budget see the same three ``llm_*`` handles either way.

``structured`` is the workhorse. Smaller models are markedly worse at schema
adherence than frontier models, so a single ``with_structured_output`` call is
not reliable enough to build a pipeline on. This helper degrades through three
strategies before giving up, and returns ``None`` rather than raising so the
supervisor can drop one topic instead of failing the whole run.
"""

from __future__ import annotations

import json
import os
import re
from typing import TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, ValidationError

from newsroom.config import MODELS

T = TypeVar("T", bound=BaseModel)

# OpenRouter is OpenAI-compatible; these headers are the courtesy attribution it
# asks integrations to send. They are optional and carry nothing sensitive.
_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://github.com/ekambaranath/weeklyNewsAI",
    "X-Title": "This Week in AI",
}

BACKEND = str(MODELS.get("backend", "ollama")).lower()


def _build_ollama(model_name: str, temperature: float) -> BaseChatModel:
    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=model_name,
        base_url=MODELS["host"],
        temperature=temperature,
        num_ctx=MODELS["num_ctx"],
    )


def _build_openrouter(model_name: str, temperature: float) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        raise RuntimeError(
            "backend = \"openrouter\" but $OPENROUTER_API_KEY is not set. Export "
            "your key (get a free one at https://openrouter.ai/keys) before "
            "running, or switch [models] backend back to \"ollama\" in config.toml."
        )
    return ChatOpenAI(
        model=model_name,
        base_url=_OPENROUTER_BASE,
        api_key=key,
        temperature=temperature,
        max_tokens=int(MODELS.get("max_tokens", 4096)),
        default_headers=_OPENROUTER_HEADERS,
        timeout=180,
        max_retries=3,
    )


def _tier(name: str) -> str:
    """Resolve a tier's model id for the active backend.

    Ollama and OpenRouter name models differently, so each backend keeps its own
    ids in config: ``ollama_strong`` etc. for Ollama, plain ``strong`` etc. for
    OpenRouter. The ``ollama_*`` keys fall back to the plain ones if absent.
    """
    if BACKEND == "ollama":
        return MODELS.get(f"ollama_{name}", MODELS[name])
    return MODELS[name]


def _build(name: str, temperature: float) -> BaseChatModel:
    model_name = _tier(name)
    if BACKEND == "openrouter":
        return _build_openrouter(model_name, temperature)
    if BACKEND == "ollama":
        return _build_ollama(model_name, temperature)
    raise RuntimeError(
        f"unknown [models] backend {BACKEND!r} — use \"ollama\" or \"openrouter\"."
    )


# Tier 1 — Managing Editor. Judgement and prose. The only place worth the RAM.
llm_strong = _build("strong", MODELS["temperature_strong"])
# Tier 2 — Leads. Allocation and adjudication: structured, moderate reasoning.
llm_mid = _build("mid", MODELS["temperature_mid"])
# Tier 3 — Workers. Bounded, high-volume, near-mechanical.
llm_small = _build("small", MODELS["temperature_small"])


_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

# Transport/runtime errors are swallowed so one bad reply costs one topic, not
# the run — but a run where EVERY call fails then looks identical to a run where
# the models simply had nothing to say. So the last error is kept here, and
# printed immediately when NEWSROOM_DEBUG is set, to make that difference visible.
LAST_ERROR: str = ""
_DEBUG = bool(os.environ.get("NEWSROOM_DEBUG"))


def _note_error(where: str, exc: Exception) -> None:
    global LAST_ERROR
    LAST_ERROR = f"{where}: {type(exc).__name__}: {exc}"
    if _DEBUG:
        import sys

        print(f"  [llm-error] {LAST_ERROR}", file=sys.stderr, flush=True)


def list_free_models(substr: str = "") -> list[str]:
    """Free model ids currently served by OpenRouter, optionally filtered.

    Hits the public models endpoint (no key required). Used by ``--check`` to
    name a valid replacement slug when the configured one 404s, so a slug that
    OpenRouter has renamed or retired can be fixed without guessing.
    """
    import urllib.request

    try:
        req = urllib.request.Request(
            f"{_OPENROUTER_BASE}/models", headers={"Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except Exception as exc:
        return [f"(could not list models: {type(exc).__name__}: {exc})"]

    out = []
    for m in data.get("data", []):
        mid = m.get("id", "")
        pr = m.get("pricing", {}) or {}
        free = str(pr.get("prompt", "1")) in ("0", "0.0") and str(
            pr.get("completion", "1")
        ) in ("0", "0.0")
        if free and (not substr or substr.lower() in mid.lower()):
            out.append(mid)
    return sorted(out)


def check() -> tuple[bool, str]:
    """One live round-trip on the strong tier. Returns (ok, detail).

    Used by ``run.py --check`` so a misconfigured key, an unavailable model or a
    blocked data policy surfaces as a plain message instead of an empty edition.
    """
    try:
        reply = llm_strong.invoke(
            [("system", "Reply with the single word: ok"), ("human", "ready?")]
        ).content
        text = reply if isinstance(reply, str) else str(reply)
        return True, text.strip()[:200]
    except Exception as exc:  # surface the real cause, including any HTTP body
        detail = f"{type(exc).__name__}: {exc}"
        body = getattr(getattr(exc, "response", None), "text", None)
        if body:
            detail += f"\n  body: {body[:600]}"
        return False, detail


def _salvage_json(text: str) -> dict | list | None:
    """Last-resort extraction of a JSON object from a chatty model reply."""
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1)
    start = min(
        (i for i in (text.find("{"), text.find("[")) if i != -1),
        default=-1,
    )
    if start == -1:
        return None
    # Walk back from the end for the matching close, tolerating trailing prose.
    for end in range(len(text), start, -1):
        chunk = text[start:end]
        if chunk.rstrip()[-1:] not in "}]":
            continue
        try:
            return json.loads(chunk)
        except json.JSONDecodeError:
            continue
    return None


def structured(
    llm: BaseChatModel,
    schema: type[T],
    system: str,
    user: str,
    *,
    budget=None,
    label: str = "",
) -> T | None:
    """Call `llm` and coerce the reply into `schema`, or return None.

    Strategy ladder, cheapest-first:
      1. native json_schema constrained decoding (best when the model supports it)
      2. json_mode, which is looser but more widely supported
      3. plain call + regex/brace salvage + Pydantic validation

    Returning None instead of raising is deliberate. In a fan-out of five
    researchers, one malformed reply should cost one topic, not the run.
    """
    messages = [("system", system), ("human", user)]

    for method in ("json_schema", "json_mode"):
        if budget is not None and not budget.spend(label or schema.__name__):
            return None
        try:
            out = llm.with_structured_output(schema, method=method).invoke(messages)
            if isinstance(out, schema):
                return out
            if isinstance(out, dict):
                return schema.model_validate(out)
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            _note_error(f"{label or schema.__name__}/{method}", exc)
            continue
        except Exception as exc:  # transport/runtime issues: fall to the next rung
            _note_error(f"{label or schema.__name__}/{method}", exc)
            continue

    if budget is not None and not budget.spend(label or schema.__name__):
        return None
    try:
        raw = llm.invoke(messages).content
        payload = _salvage_json(raw if isinstance(raw, str) else str(raw))
        if payload is None:
            return None
        return schema.model_validate(payload)
    except Exception as exc:
        _note_error(f"{label or schema.__name__}/plain", exc)
        return None


def prose(llm: BaseChatModel, system: str, user: str, *, budget=None, label: str = "") -> str:
    """Free-text call, used only where the output IS the product (the report)."""
    if budget is not None and not budget.spend(label or "prose"):
        return ""
    try:
        out = llm.invoke([("system", system), ("human", user)]).content
        return out if isinstance(out, str) else str(out)
    except Exception as exc:
        _note_error(label or "prose", exc)
        return ""
