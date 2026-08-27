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
        except (ValidationError, ValueError, TypeError, KeyError):
            continue
        except Exception:  # transport/runtime issues: fall through to the next rung
            continue

    if budget is not None and not budget.spend(label or schema.__name__):
        return None
    try:
        raw = llm.invoke(messages).content
        payload = _salvage_json(raw if isinstance(raw, str) else str(raw))
        if payload is None:
            return None
        return schema.model_validate(payload)
    except Exception:
        return None


def prose(llm: BaseChatModel, system: str, user: str, *, budget=None, label: str = "") -> str:
    """Free-text call, used only where the output IS the product (the report)."""
    if budget is not None and not budget.spend(label or "prose"):
        return ""
    try:
        out = llm.invoke([("system", system), ("human", user)]).content
        return out if isinstance(out, str) else str(out)
    except Exception:
        return ""
