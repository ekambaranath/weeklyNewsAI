"""Local model tiers, mapped to the agent hierarchy.

Three Ollama models, one per tier. Nothing here talks to a paid API, so a run
costs zero dollars — but see budget.py: local inference still spends wall-clock
and RAM, and those are the resources that actually run out.

``structured`` is the workhorse. Small local models are markedly worse at
schema adherence than frontier models, so a single ``with_structured_output``
call is not reliable enough to build a pipeline on. This helper degrades through
three strategies before giving up, and returns ``None`` rather than raising so
the supervisor can drop one topic instead of failing the whole run.
"""

from __future__ import annotations

import json
import re
from typing import TypeVar

from langchain_ollama import ChatOllama
from pydantic import BaseModel, ValidationError

from newsroom.config import MODELS

T = TypeVar("T", bound=BaseModel)


def _build(model_name: str, temperature: float) -> ChatOllama:
    return ChatOllama(
        model=model_name,
        base_url=MODELS["host"],
        temperature=temperature,
        num_ctx=MODELS["num_ctx"],
    )


# Tier 1 — Managing Editor. Judgement and prose. The only place worth the RAM.
llm_strong = _build(MODELS["strong"], MODELS["temperature_strong"])
# Tier 2 — Leads. Allocation and adjudication: structured, moderate reasoning.
llm_mid = _build(MODELS["mid"], MODELS["temperature_mid"])
# Tier 3 — Workers. Bounded, high-volume, near-mechanical.
llm_small = _build(MODELS["small"], MODELS["temperature_small"])


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
    llm: ChatOllama,
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


def prose(llm: ChatOllama, system: str, user: str, *, budget=None, label: str = "") -> str:
    """Free-text call, used only where the output IS the product (the report)."""
    if budget is not None and not budget.spend(label or "prose"):
        return ""
    try:
        out = llm.invoke([("system", system), ("human", user)]).content
        return out if isinstance(out, str) else str(out)
    except Exception:
        return ""
