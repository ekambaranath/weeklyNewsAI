"""Tier 0 — the deterministic orchestrator.

This is the layer that makes the hierarchy cheap. In the original design the
fan-out, the quality gate and the retry cap all lived as English instructions
inside the strongest model's system prompt, which means you pay a reasoning
model to do routing, and the "hard cap" on retries is a polite request the model
can ignore.

Here they are graph edges. ``Send`` fans out to parallel workers, a conditional
edge governs the verify loop, and the retry cap is an integer compared in Python
— enforced, not requested. The models are left with the two things they are
actually for: deciding what matters, and writing it well.
"""

from __future__ import annotations

import operator
from datetime import date
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from newsroom import agents, harvest, memory
from newsroom import cluster as clustering
from newsroom.budget import Budget
from newsroom.citations import renumber
from newsroom.config import BUDGET
from newsroom.gates import GateResult, format_gates, run_gates, sensitive_flags
from newsroom.schemas import (
    Assignment,
    Brief,
    Cluster,
    EditorialPlan,
    Item,
    VerificationReport,
)


def _keep_latest(existing: list, incoming: list) -> list:
    """Reducer: later rounds supersede earlier ones for the same cluster."""
    merged = {getattr(x, "cluster_id", id(x)): x for x in existing}
    for item in incoming:
        merged[getattr(item, "cluster_id", id(item))] = item
    return list(merged.values())


class RunState(TypedDict, total=False):
    run_date: str
    budget: Budget
    items: list[Item]
    clusters: list[Cluster]
    plan: EditorialPlan
    assignments: list[Assignment]
    briefs: Annotated[list[Brief], _keep_latest]
    reports: Annotated[list[VerificationReport], _keep_latest]
    verify_round: int
    report: str
    gate_results: list[GateResult]
    warnings: Annotated[list[str], operator.add]
    review_issues: list[str]
    revised: bool


# ------------------------------------------------------------------- nodes


def node_harvest(state: RunState) -> dict:
    items = harvest.harvest()
    return {
        "items": items,
        "warnings": [] if items else ["harvest returned nothing — check connectivity"],
    }


def node_cluster(state: RunState) -> dict:
    clusters = clustering.label_continuity(clustering.build_clusters(state["items"]))
    # Brief the editor on a shortlist; deeper clusters are already ranked lower.
    return {"clusters": clusters[: int(BUDGET["max_topics"]) * 3]}


def node_triage(state: RunState) -> dict:
    plan = agents.editor_triage(state["clusters"], state["budget"])
    return {"plan": plan}


def node_allocate(state: RunState) -> dict:
    prior = memory.prior_summaries()
    assignments = agents.research_lead_allocate(state["plan"], prior, state["budget"])
    return {"assignments": assignments, "verify_round": 0}


def fan_out_research(state: RunState) -> list[Send] | str:
    """Tier 0 routing: one parallel worker per assignment. No model involved."""
    assignments = state.get("assignments") or []
    if not assignments:
        return "publish"
    by_id = {c.cluster_id: c for c in state["clusters"]}
    return [
        Send("research", {"assignment": a, "cluster": by_id[a.cluster_id], "budget": state["budget"]})
        for a in assignments
        if a.cluster_id in by_id
    ]


def node_research(payload: dict) -> dict:
    brief = agents.researcher_work(
        payload["assignment"],
        payload["cluster"],
        payload["budget"],
        round_no=payload.get("round", 0),
    )
    return {"briefs": [brief]}


def node_quality_gate(state: RunState) -> dict:
    """Deterministic drop of SKIP verdicts. Free, and not a judgement call."""
    kept = [b for b in state.get("briefs", []) if b.verdict == "KEEP" and b.claims]
    dropped = len(state.get("briefs", [])) - len(kept)
    return {
        "briefs": kept,
        "warnings": [f"quality gate dropped {dropped} topic(s)"] if dropped else [],
    }


def fan_out_verify(state: RunState) -> list[Send] | str:
    briefs = state.get("briefs") or []
    if not briefs:
        return "publish"
    return [Send("verify", {"brief": b, "budget": state["budget"]}) for b in briefs]


def node_verify(payload: dict) -> dict:
    return {"reports": [agents.verify_topic(payload["brief"], payload["budget"])]}


def route_after_verify(state: RunState) -> str:
    """The retry cap, enforced in Python rather than requested in a prompt."""
    flagged = [r for r in state.get("reports", []) if r.result == "FLAG"]
    round_no = state.get("verify_round", 0)
    if flagged and round_no < int(BUDGET["max_verify_rounds"]):
        return "redispatch"
    return "prune"


def node_redispatch(state: RunState) -> dict:
    """Re-arm assignments for exactly the flagged topics, with the gaps named."""
    flagged = {r.cluster_id: r for r in state.get("reports", []) if r.result == "FLAG"}
    rearmed = []
    for a in state.get("assignments", []):
        if a.cluster_id in flagged:
            a.unsupported_claims = flagged[a.cluster_id].unsupported
            rearmed.append(a)
    return {"assignments": rearmed, "verify_round": state.get("verify_round", 0) + 1}


def fan_out_redispatch(state: RunState) -> list[Send] | str:
    assignments = state.get("assignments") or []
    if not assignments:
        return "prune"
    by_id = {c.cluster_id: c for c in state["clusters"]}
    round_no = state.get("verify_round", 0)
    return [
        Send(
            "research",
            {
                "assignment": a,
                "cluster": by_id[a.cluster_id],
                "budget": state["budget"],
                "round": round_no,
            },
        )
        for a in assignments
        if a.cluster_id in by_id
    ]


def node_prune(state: RunState) -> dict:
    """Drop every claim still unsupported after the final allowed round.

    Never invent support to save a claim; if a topic's substance depended on the
    dropped claims, the topic goes with them.
    """
    unsupported: dict[str, set[str]] = {
        r.cluster_id: set(r.unsupported) for r in state.get("reports", [])
    }
    kept: list[Brief] = []
    removed = 0
    for brief in state.get("briefs", []):
        bad = unsupported.get(brief.cluster_id, set())
        surviving = [c for c in brief.claims if c.text not in bad]
        removed += len(brief.claims) - len(surviving)
        if surviving:
            brief.claims = surviving
            kept.append(brief)
    return {
        "briefs": kept,
        "warnings": [f"pruned {removed} unverifiable claim(s)"] if removed else [],
    }


def node_synthesise(state: RunState) -> dict:
    briefs = state.get("briefs", [])
    if not briefs:
        return {"report": "", "warnings": ["nothing survived verification — no report"]}
    raw = agents.editor_synthesise(briefs, state["plan"], state["run_date"], state["budget"])
    meta = {
        c.source_url.rstrip("/"): f"{c.source_url}"
        for b in briefs
        for c in b.claims
    }
    report, warns = renumber(raw, meta)
    return {"report": report, "warnings": warns}


def node_gates(state: RunState) -> dict:
    report = state.get("report", "")
    if not report:
        return {"gate_results": []}
    _, results = run_gates(report)
    flags = sensitive_flags(report)
    return {
        "gate_results": results,
        "warnings": [f"sensitive terms present: {', '.join(flags)}"] if flags else [],
    }


def route_after_gates(state: RunState) -> str:
    """Skip the LLM reviewer entirely on a clean run. This is the free win."""
    results = state.get("gate_results", [])
    if not results:
        return "finish"
    if all(r.passed for r in results) and not state.get("revised"):
        return "finish"
    if state.get("revised"):
        return "finish"  # one revision round only
    return "review"


def node_review(state: RunState) -> dict:
    verdict = agents.publish_review(
        state["report"], format_gates(state.get("gate_results", [])), state["budget"]
    )
    if verdict.approve and not verdict.issues:
        return {"revised": True}
    revised = agents.editor_revise(state["report"], verdict.issues, state["budget"])
    report, warns = renumber(revised)
    return {"report": report, "revised": True, "review_issues": verdict.issues, "warnings": warns}


def node_finish(state: RunState) -> dict:
    return {}


# -------------------------------------------------------------------- graph


def build_graph():
    g = StateGraph(RunState)

    g.add_node("harvest", node_harvest)
    g.add_node("cluster", node_cluster)
    g.add_node("triage", node_triage)
    g.add_node("allocate", node_allocate)
    g.add_node("research", node_research)
    g.add_node("quality_gate", node_quality_gate)
    g.add_node("verify", node_verify)
    g.add_node("redispatch", node_redispatch)
    g.add_node("prune", node_prune)
    g.add_node("publish", node_synthesise)
    g.add_node("gates", node_gates)
    g.add_node("review", node_review)
    g.add_node("finish", node_finish)

    g.add_edge(START, "harvest")
    g.add_edge("harvest", "cluster")
    g.add_edge("cluster", "triage")
    g.add_edge("triage", "allocate")

    g.add_conditional_edges("allocate", fan_out_research, ["research", "publish"])
    g.add_edge("research", "quality_gate")
    g.add_conditional_edges("quality_gate", fan_out_verify, ["verify", "publish"])
    g.add_conditional_edges("verify", route_after_verify, ["redispatch", "prune"])
    g.add_conditional_edges("redispatch", fan_out_redispatch, ["research", "prune"])

    g.add_edge("prune", "publish")
    g.add_edge("publish", "gates")
    g.add_conditional_edges("gates", route_after_gates, ["review", "finish"])
    g.add_edge("review", "gates")
    g.add_edge("finish", END)

    return g.compile()


def initial_state(run_date: str | None = None) -> RunState:
    return {
        "run_date": run_date or date.today().isoformat(),
        "budget": Budget(),
        "briefs": [],
        "reports": [],
        "warnings": [],
        "verify_round": 0,
        "revised": False,
    }
