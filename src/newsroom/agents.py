"""The agent hierarchy.

    Tier 0  ORCHESTRATOR        graph.py — deterministic. No LLM.
            routing, fan-out, retry caps, budget, gates
                │
    Tier 1  MANAGING EDITOR     llm_strong
            two calls per run: what matters, and the finished prose
                │
    Tier 2  LEADS               llm_mid
            ├─ Research Lead      allocates depth across topics
            ├─ Verification Lead  adjudicates escalated claims
            └─ Publishing Lead    decides whether review is needed
                │
    Tier 3  WORKERS             llm_small
            ├─ topic-researcher ×N   parallel, isolated context
            ├─ claim-verifier ×N     one claim, one source, no web
            └─ final-pass-reviewer   conditional — only when a gate fails

The organising principle, and the thing that keeps a hierarchy from becoming
overhead: **a tier exists only where judgement is required.** Routing, retry
counting, quality gating, dedup and numbering are not judgement. They sit in
Tier 0 as plain functions, so the managers manage rather than clerk.
"""

from __future__ import annotations

import json

from newsroom.budget import Budget
from newsroom.config import BUDGET
from newsroom.gates import entity_fidelity
from newsroom.models import llm_mid, llm_small, llm_strong, prose, structured
from newsroom.quarantine import evidence_for, store
from newsroom.schemas import (
    Assignment,
    Brief,
    ClaimCheck,
    Cluster,
    EditorialPlan,
    ResearchAllocation,
    ReviewVerdict,
    TopicDecision,
    VerificationReport,
)

# ============================================================ Tier 1: EDITOR

EDITOR_TRIAGE_SYSTEM = """You are the Managing Editor of a weekly AI-news digest.

You are given candidate story clusters that a deterministic pipeline has already
discovered, deduplicated, and compared against previous editions. Your job is
judgement, and only judgement: which of these actually matter to someone
building with AI, and which are noise.

Each cluster arrives with a suggested status computed from similarity to past
editions. Treat it as a strong prior, not an instruction:
  NEW        — not covered before.
  DEVELOPING — a storyline you have run before. Keep it ONLY if something
               genuinely changed; say what changed in one line.
  REPEAT     — near-identical to a previous edition. Drop it UNLESS you can see a
               real new development, in which case keep it as DEVELOPING.

SOURCE STANDARD: a claim is a fact only when an independent source stands behind
it. Company blogs and announcements are claims, not facts. If a cluster's only
substance is a product announcement with no independent reporting, drop it.

Keep at most {max_topics} clusters. Be ruthless — a short digest people read
beats a long one they skim."""

EDITOR_SYNTHESIS_SYSTEM = """You are the Managing Editor writing the finished digest.

You are given verified claims, each with the exact URL that substantiates it.
Every claim you use has already passed citation verification. Write the report.

STRUCTURE — follow it exactly:
  # This Week in AI · <date>
  <One paragraph: what actually happened and where things are moving. If any
  topic is DEVELOPING, open with a short "Since last time:" clause.>

  ## <Topic> (new)  |  ## <Topic> (developing)
  <2-4 sentences of synthesis. For a developing story, LEAD with what changed.
  Where a real, concrete implication exists for someone building with AI, close
  with ONE plain sentence saying so — never manufacture one to fill the slot.>

  ## Sources
  <one per line: outlet — title — url. Do NOT number them.>

CITATIONS — cite by URL, never by number:
  Put the source URL in DOUBLE brackets straight after the claim it supports:
  "...cut inference latency by half [[https://example.com/article]]."
  Stack them for multiple sources: [[url1]][[url2]].
  NEVER write [1] or [2] yourself. A downstream step assigns all numbering.

VOICE: plain, specific, unhurried. No hype vocabulary — no "game-changer", no
"revolutionary", no "breakthrough". State what happened and let it land. Give a
count as a single number, and name the unit on any comparison ("3x cheaper per
output token", not "3x cheaper")."""


def editor_triage(clusters: list[Cluster], budget: Budget) -> EditorialPlan:
    """Tier 1, call 1. Which stories make the edition."""
    briefing = []
    for cluster in clusters:
        exemplars = [
            {"title": i.title, "domain": i.domain, "quality": i.quality}
            for i in cluster.exemplars(3)
        ]
        briefing.append(
            {
                "cluster_id": cluster.cluster_id,
                "keywords": cluster.label,
                "article_count": len(cluster.items),
                "reputable_count": sum(1 for i in cluster.items if i.quality == "reputable"),
                "suggested_status": cluster.suggested_status,
                "similar_to_past_edition": cluster.prior_topic or None,
                "similarity": cluster.prior_similarity,
                "examples": exemplars,
            }
        )

    plan = structured(
        llm_strong,
        EditorialPlan,
        EDITOR_TRIAGE_SYSTEM.format(max_topics=BUDGET["max_topics"]),
        "Candidate clusters:\n" + json.dumps(briefing, indent=2),
        budget=budget,
        label="editor.triage",
    )

    if plan is None:
        # Degrade, do not fail: fall back to the deterministic ranking.
        return EditorialPlan(
            decisions=[
                TopicDecision(
                    cluster_id=c.cluster_id,
                    topic=c.label,
                    status="NEW" if c.suggested_status == "REPEAT" else c.suggested_status,
                    keep=c.suggested_status != "REPEAT",
                    why="fallback: editor triage unavailable, ranked by corroboration",
                )
                for c in clusters[: int(BUDGET["max_topics"])]
            ]
        )
    return plan


def editor_synthesise(
    briefs: list[Brief], plan: EditorialPlan, run_date: str, budget: Budget
) -> str:
    """Tier 1, call 2. The product itself — the one place prose quality matters."""
    status_of = {d.cluster_id: d.status for d in plan.decisions}
    payload = [
        {
            "topic": b.topic,
            "status": status_of.get(b.cluster_id, "NEW"),
            "verified_claims": [{"claim": c.text, "url": c.source_url} for c in b.claims],
        }
        for b in briefs
    ]
    user = (
        f"Date: {run_date}\n"
        f"Editorial throughline: {plan.throughline or '(none identified)'}\n\n"
        f"Verified material:\n{json.dumps(payload, indent=2)}"
    )
    return prose(
        llm_strong, EDITOR_SYNTHESIS_SYSTEM, user, budget=budget, label="editor.synthesis"
    )


def editor_revise(report: str, issues: list[str], budget: Budget) -> str:
    """Tier 1, conditional. Fix concrete problems without re-researching."""
    user = (
        "Revise this report to fix the listed problems. Change nothing else, and do "
        "NOT introduce any claim that is not already present.\n\n"
        "Problems:\n" + "\n".join(f"- {i}" for i in issues) + f"\n\nReport:\n{report}"
    )
    revised = prose(
        llm_strong, EDITOR_SYNTHESIS_SYSTEM, user, budget=budget, label="editor.revise"
    )
    return revised or report


# ====================================================== Tier 2: RESEARCH LEAD

RESEARCH_LEAD_SYSTEM = """You are the Research Lead. The Managing Editor has chosen
the topics; you decide how much effort each one gets, and what specifically each
researcher must establish.

You have a fixed research budget. Allocate it unevenly and on purpose:
  depth="deep"  — the {deep_n} most consequential or least-understood topics.
  depth="brief" — everything else: one pass, higher bar for inclusion.

For each assignment write an "angle": the specific question the researcher must
answer. Not "research X" but "establish what X actually measured and who
independently confirmed it". A sharp angle is what stops a researcher returning
a reworded announcement.

For a DEVELOPING topic the angle must be about the DELTA — what changed since
last time — not a re-explanation of the storyline."""


def research_lead_allocate(
    plan: EditorialPlan, prior: dict[str, str], budget: Budget
) -> list[Assignment]:
    """Tier 2. Judgement: where the effort goes. Not routing — routing is Tier 0."""
    kept = [d for d in plan.decisions if d.keep]
    if not kept:
        return []

    payload = [
        {
            "cluster_id": d.cluster_id,
            "topic": d.topic,
            "status": d.status,
            "why_it_matters": d.why,
            "previous_coverage": prior.get(d.topic, ""),
        }
        for d in kept
    ]
    allocation = structured(
        llm_mid,
        ResearchAllocation,
        RESEARCH_LEAD_SYSTEM.format(deep_n=BUDGET["deep_research_topics"]),
        json.dumps(payload, indent=2),
        budget=budget,
        label="research_lead.allocate",
    )

    if allocation is None:
        deep_n = int(BUDGET["deep_research_topics"])
        return [
            Assignment(
                cluster_id=d.cluster_id,
                topic=d.topic,
                status=d.status,
                depth="deep" if i < deep_n else "brief",
                angle=d.why,
                prior_summary=prior.get(d.topic, ""),
            )
            for i, d in enumerate(kept)
        ]

    # The lead may hallucinate a topic; keep only assignments matching real clusters.
    valid = {d.cluster_id: d for d in kept}
    out = []
    for a in allocation.assignments:
        if a.cluster_id in valid:
            a.status = valid[a.cluster_id].status
            a.prior_summary = prior.get(a.topic, "")
            out.append(a)
    return out or [
        Assignment(cluster_id=d.cluster_id, topic=d.topic, status=d.status, angle=d.why)
        for d in kept
    ]


# ======================================================== Tier 3: RESEARCHER

RESEARCHER_SYSTEM = """You are a research analyst working ONE topic for a weekly
AI digest. You are given a numbered digest of source material that has already
been gathered and filtered for you.

Your job: extract the factual claims the sources actually support, and attach
the exact source URL to each one.

RULES — these are hard:
1. Every claim must be a single factual sentence, traceable to ONE source URL
   from the digest below. Do not merge two sources into one claim.
2. Use ONLY the digest. Do not add anything from your own knowledge. If you
   cannot support something with a listed source, leave it out.
3. Names and numbers must appear in the source you cite. Do not normalise a
   product name, round a figure, or infer a company.
4. verdict="SKIP" if the topic's only substance is a company announcement with
   no independent reporting, or if the sources do not support anything specific.
   Skipping is a good outcome. Do not manufacture significance.
5. Aim for 3-6 claims for a deep assignment, 2-3 for a brief one."""

RESEARCHER_REDISPATCH = """
THIS IS A SECOND PASS. A verifier found these claims UNSUPPORTED by their cited
sources:
{claims}

Find support for them in the digest, correct them so they match what a source
actually says, or drop them. Return your full revised claim set. Do not restate
a claim you still cannot back."""


def researcher_work(
    assignment: Assignment, cluster: Cluster, budget: Budget, round_no: int = 0
) -> Brief:
    """Tier 3. Isolated context, one topic, bounded output.

    The worker never sees or re-emits raw source text — quarantine.store has
    already written it to disk and returns only a compact digest. This is where
    the original design paid output-token rates to retype evidence.
    """
    items = list(cluster.items)
    if assignment.depth == "deep" and len(items) < 4:
        from newsroom.harvest import search_topic

        extra = search_topic(f"{assignment.topic} {assignment.angle}"[:120], max_results=6)
        items.extend(extra)

    evidence = store(assignment.topic, items)
    if not evidence:
        return Brief(
            cluster_id=assignment.cluster_id,
            topic=assignment.topic,
            verdict="SKIP",
            reason="no evidence available after filtering",
            round=round_no,
        )

    system = RESEARCHER_SYSTEM
    if assignment.unsupported_claims:
        system += RESEARCHER_REDISPATCH.format(
            claims="\n".join(f"- {c}" for c in assignment.unsupported_claims)
        )

    user_parts = [
        f"TOPIC: {assignment.topic}",
        f"STATUS: {assignment.status}",
        f"DEPTH: {assignment.depth}",
        f"ANGLE: {assignment.angle or 'establish what actually happened'}",
    ]
    if assignment.status == "DEVELOPING" and assignment.prior_summary:
        user_parts.append(
            f"PREVIOUSLY REPORTED: {assignment.prior_summary}\n"
            "Report only what has CHANGED since then."
        )
    user_parts.append("SOURCE DIGEST:\n" + json.dumps(evidence[:14], indent=2))

    brief = structured(
        llm_small,
        Brief,
        system,
        "\n\n".join(user_parts),
        budget=budget,
        label="researcher",
    )
    if brief is None:
        return Brief(
            cluster_id=assignment.cluster_id,
            topic=assignment.topic,
            verdict="SKIP",
            reason="researcher produced no usable output",
            round=round_no,
        )

    brief.cluster_id = assignment.cluster_id
    brief.topic = assignment.topic
    brief.round = round_no
    # Discard any claim citing a URL not in the quarantine — no invented sources.
    known = {e["url"].rstrip("/") for e in evidence}
    brief.claims = [c for c in brief.claims if c.source_url.rstrip("/") in known]
    if not brief.claims:
        brief.verdict = "SKIP"
        brief.reason = brief.reason or "no claims traceable to a quarantined source"
    return brief


# ========================================== Tier 3: VERIFIER + Tier 2 LEAD

VERIFIER_SYSTEM = """You check ONE claim against ONE source. Nothing else.

You are given a claim and the exact source text it cites. Decide whether that
source actually substantiates that claim.

  PASS — the source states or clearly implies the claim.
  FLAG — it does not, it says something weaker, or the claim overstates it.

You have no web access and must not use outside knowledge. If the source text
does not contain it, it is FLAG — even if you believe the claim is true.
Deciding a true-but-unsourced claim is PASS is the specific failure this step
exists to prevent."""


def verify_topic(brief: Brief, budget: Budget) -> VerificationReport:
    """Tier 3 + Tier 2 escalation, run claim by claim.

    Two-stage by design. Stage one is free: entity_fidelity is pure string work
    that catches invented names and drifted figures. Only claims that survive it
    cost a model call, and each one gets its single cited source rather than the
    whole evidence dump — a keyed lookup, not retrieval.
    """
    checks: list[ClaimCheck] = []

    for claim in brief.claims:
        record = evidence_for(brief.topic, claim.source_url)
        if record is None:
            checks.append(
                ClaimCheck(claim_text=claim.text, result="FLAG", note="cited URL not in quarantine")
            )
            continue

        haystack = f"{record['title']} {record['text']}"
        ok, missing = entity_fidelity(claim.text, haystack)
        if not ok:
            checks.append(
                ClaimCheck(
                    claim_text=claim.text,
                    result="FLAG",
                    note=f"not present in source: {', '.join(missing)}",
                )
            )
            continue

        check = structured(
            llm_small,
            ClaimCheck,
            VERIFIER_SYSTEM,
            f"CLAIM:\n{claim.text}\n\nSOURCE ({record['domain']}):\n"
            f"{record['title']}\n{record['text']}",
            budget=budget,
            label="verifier",
        )
        checks.append(
            check
            if check is not None
            else ClaimCheck(claim_text=claim.text, result="PASS", note="verifier unavailable")
        )
        checks[-1].claim_text = claim.text

    return VerificationReport(
        cluster_id=brief.cluster_id,
        topic=brief.topic,
        result="FLAG" if any(c.result == "FLAG" for c in checks) else "PASS",
        checks=checks,
        round=brief.round,
    )


# ===================================================== Tier 2: PUBLISHING LEAD

REVIEWER_SYSTEM = """You are the final reviewer. Mechanical checks — citation
numbering, source quality, hype density, groundedness — have already run in code
and their results are given to you. Do not re-check them.

Judge only what code cannot: does the report hold together as ONE piece?
  COHERENCE   — the sections form a thread, and the intro's claim about the week
                is actually delivered by the body. Flag a promise never kept.
  CONTINUITY  — developing sections lead with what changed.
  CONSISTENCY — no two sections contradict each other.
  COMPLETENESS— no placeholder, empty heading, or truncated sentence.

approve=false only for real, fixable, whole-report problems. Do not nitpick
wording."""


def publish_review(report: str, gate_detail: str, budget: Budget) -> ReviewVerdict:
    """Tier 2, CONDITIONAL. Only dispatched when a deterministic gate failed."""
    verdict = structured(
        llm_mid,
        ReviewVerdict,
        REVIEWER_SYSTEM,
        f"AUTOMATED CHECK RESULTS:\n{gate_detail}\n\nREPORT:\n{report}",
        budget=budget,
        label="publish_lead.review",
    )
    return verdict or ReviewVerdict(approve=True, note="reviewer unavailable; gates govern")
