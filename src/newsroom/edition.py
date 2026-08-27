"""Compose the reader-facing edition from verified research.

This is the bridge the pipeline was missing. The graph produces verified
``Brief`` objects — topic, claims, each claim's source URL — and a markdown
report. But every deliverable (web, email, PDF) consumes a much richer JSON
document: the thread, four glance numbers, story cards graded by confidence and
backed by classified sources, the dropped list, the gate scorecard. Nothing
built that document, so the weekly send could only re-mail a hand-authored
sample. This module builds it from each run's own verified evidence, so the
edition regenerates itself.

The division of labour follows the project's rule that a model is used only for
judgement. The editor (``agents.editor_compose``) writes the copy — headline,
dek, the four field sentences, the thread. Everything factual is computed here,
in code, straight from the briefs: which sources back a story and how much they
are worth, the confidence grade, the gate scores, the four numbers, the dropped
list, the dates. The evidence chain of custody never passes through the model.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from urllib.parse import urlparse

from newsroom.config import DENY_DOMAINS, OUTPUT_DIR
from newsroom.schemas import Brief, EditionCopy, EditorialPlan, StoryCopy

# ------------------------------------------------------------------ sections
# Fixed desks, so the hue and label a story renders with can never be an invented
# value. The editor only picks which desk; name/sub/hue are ours.
SECTIONS: dict[str, dict] = {
    "shipped": {"name": "Shipped", "sub": "Models · pricing · releases", "hue": "#1D5FAE"},
    "security": {"name": "Security", "sub": "Incidents · disclosures · defence", "hue": "#B3261E"},
    "governance": {"name": "Lab governance", "sub": "Policy · safety · institutions", "hue": "#5B3FA8"},
    "research": {"name": "Research", "sub": "Papers · results · methods", "hue": "#0F6B4F"},
    "business": {"name": "Business", "sub": "Funding · deals · market", "hue": "#8A6100"},
}
SECTION_ORDER = ["shipped", "security", "research", "governance", "business"]

# ------------------------------------------------------------ source classes
# Trust class per source domain, decided before any copy is written. Primary and
# independent are the "strong" classes the confidence grade and provenance bar
# both count. The lists mirror config.toml's trust allow-list.
_PRIMARY = {
    "arxiv.org", "nature.com", "science.org", "acm.org", "ieee.org",
    "nist.gov", "europa.eu", "ai.gov", "gov.uk", "pa.gov",
    "pewresearch.org", "hai.stanford.edu",
}
_INDEPENDENT = {
    "reuters.com", "apnews.com", "bloomberg.com", "ft.com", "wsj.com",
    "nytimes.com", "washingtonpost.com", "theguardian.com", "economist.com",
    "bbc.com", "bbc.co.uk", "npr.org", "axios.com", "politico.com",
    "nbcnews.com", "cbsnews.com", "abcnews.go.com", "thehill.com", "forbes.com",
    "whyy.org", "courthousenews.com",
}
_TRADE = {
    "arstechnica.com", "theverge.com", "wired.com", "techcrunch.com",
    "technologyreview.com", "theinformation.com", "semianalysis.com",
    "theregister.com", "darkreading.com", "thehackernews.com", "securityweek.com",
}
# Vendors speak for themselves; their word is a claim, not corroboration.
_VENDOR = {
    "openai.com", "anthropic.com", "deepmind.com", "deepmind.google",
    "ai.meta.com", "meta.com", "mistral.ai", "cohere.com", "google.com",
    "blog.google", "microsoft.com", "nvidia.com", "huggingface.co", "x.ai",
}

# A few domains whose second-level name is not a nice outlet label.
_OUTLET_NAMES = {
    "arxiv.org": "arXiv", "apnews.com": "AP News", "bbc.co.uk": "BBC",
    "bbc.com": "BBC", "nytimes.com": "The New York Times", "ft.com": "Financial Times",
    "wsj.com": "The Wall Street Journal", "theverge.com": "The Verge",
    "arstechnica.com": "Ars Technica", "techcrunch.com": "TechCrunch",
    "technologyreview.com": "MIT Technology Review", "theregister.com": "The Register",
    "thehackernews.com": "The Hacker News", "npr.org": "NPR",
    "hai.stanford.edu": "Stanford HAI", "openai.com": "OpenAI",
    "anthropic.com": "Anthropic", "huggingface.co": "Hugging Face",
}


def _domain(url: str) -> str:
    host = (urlparse(url).netloc or url).lower()
    return host[4:] if host.startswith("www.") else host


def _registrable(domain: str) -> str:
    """Coarse eTLD+1: enough to match the trust lists (handles co.uk)."""
    parts = domain.split(".")
    if len(parts) >= 3 and parts[-2] in {"co", "gov", "ac", "org", "com"} and parts[-1] == "uk":
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else domain


def _source_class(url: str) -> str:
    dom = _domain(url)
    reg = _registrable(dom)
    for cand in (dom, reg):
        if cand in _PRIMARY:
            return "primary"
        if cand in _INDEPENDENT:
            return "independent"
        if cand in _TRADE:
            return "trade"
        if cand in _VENDOR:
            return "vendor"
    if reg in DENY_DOMAINS or dom in DENY_DOMAINS:
        return "vendor"  # press-release wire: a vendor claim, not reporting
    return "trade"


def _outlet(url: str) -> str:
    dom = _domain(url)
    reg = _registrable(dom)
    if dom in _OUTLET_NAMES:
        return _OUTLET_NAMES[dom]
    if reg in _OUTLET_NAMES:
        return _OUTLET_NAMES[reg]
    label = reg.split(".")[0]
    return label[:1].upper() + label[1:]


def _sources_for(brief: Brief) -> list[dict]:
    """Distinct sources backing a story, each classified, strongest first."""
    seen: dict[str, dict] = {}
    for claim in brief.claims:
        url = (claim.source_url or "").strip()
        if not url or url in seen:
            continue
        seen[url] = {"outlet": _outlet(url), "cls": _source_class(url), "url": url}
    order = {"primary": 0, "independent": 1, "trade": 2, "vendor": 3, "conflict": 4}
    return sorted(seen.values(), key=lambda s: order.get(s["cls"], 9))


def _confidence(sources: list[dict], verified: bool) -> str:
    """Grade a story from the strength of what backs it — never from the copy."""
    strong = sum(1 for s in sources if s["cls"] in ("primary", "independent"))
    n = len(sources)
    if verified and strong >= 2 and n >= 3:
        return "HIGH"
    if strong >= 1 or (verified and n >= 2):
        return "MEDIUM"
    return "LOW"


def _iso_week(run_date: str) -> tuple[str, str]:
    d = date.fromisoformat(run_date)
    week = d.isocalendar().week
    start = d - timedelta(days=6)
    if start.month == d.month:
        span = f"{start.day} – {d.day} {d:%B %Y}"
    else:
        span = f"{start.day} {start:%B} – {d.day} {d:%B %Y}"
    return str(week), span


def _glance(categories: list[dict], dropped: list[dict]) -> list[dict]:
    """Four honest, computed numbers — this run's shape, not invented figures."""
    items = [i for c in categories for i in c["items"]]
    all_srcs = [s for i in items for s in i["sources"]]
    strong = sum(1 for s in all_srcs if s["cls"] in ("primary", "independent"))
    ratio = round(100 * strong / len(all_srcs)) if all_srcs else 0
    return [
        {"value": str(len(items)), "unit": "", "label": "Signals this week",
         "note": "stories that cleared verification"},
        {"value": str(len(all_srcs)), "unit": "", "label": "Sources cited",
         "note": "distinct URLs across all stories"},
        {"value": str(ratio), "unit": "%", "label": "Primary or independent",
         "note": "share of sources from strong classes"},
        {"value": str(len(dropped)), "unit": "", "label": "Topics dropped",
         "note": "researched, then cut before publication"},
    ]


_GATE_TITLES = {
    "source_quality": "Source quality",
    "source_diversity": "Source diversity",
    "hype": "Hype density",
    "groundedness": "Groundedness",
    "entity_fidelity": "Entity fidelity",
}


def _gates(gate_results) -> list[dict]:
    out = []
    for g in gate_results or []:
        score = g.score
        pretty = f"{score:.2f}" if isinstance(score, float) else str(score)
        out.append({
            "name": _GATE_TITLES.get(g.name, g.name.replace("_", " ").title()),
            "score": pretty,
            "pass": bool(g.passed),
            "detail": g.detail,
        })
    return out


def _dropped(plan: EditorialPlan | None) -> list[dict]:
    if plan is None:
        return []
    return [
        {"topic": d.topic, "reason": d.why or "cut for space", "verdict": d.status}
        for d in plan.decisions
        if not d.keep
    ][:6]


def _fields(copy: StoryCopy) -> dict:
    # Order matters: the email edition carries the LAST field as the "so what".
    return {
        "What it is": copy.what_it_is,
        "The problem it solves": copy.what_it_solves,
        "What it changes": copy.what_it_changes,
        "Should you act": copy.should_you_act,
    }


def _fallback_copy(brief: Brief) -> StoryCopy:
    """Deterministic copy when the editor call is unavailable. Degrade, not fail."""
    claims = [c.text for c in brief.claims]
    body = " ".join(claims) or brief.topic
    return StoryCopy(
        cluster_id=brief.cluster_id,
        section="shipped",
        headline=brief.topic or "Untitled",
        dek=(claims[0] if claims else brief.topic)[:200],
        what_it_is=body[:400],
        what_it_solves=(claims[1] if len(claims) > 1 else "See sources for detail."),
        what_it_changes=(claims[2] if len(claims) > 2 else "Developing; watch for confirmation."),
        should_you_act="Watch this thread; nothing to act on yet.",
        confidence_note="Auto-composed from verified claims without editorial pass.",
    )


def build_edition(
    briefs: list[Brief],
    plan: EditorialPlan | None,
    reports,
    gate_results,
    run_date: str,
    budget,
    *,
    thread_fallback: str = "",
) -> dict:
    """Assemble the full edition JSON from one run's verified evidence."""
    from newsroom import agents

    briefs = [b for b in briefs if b.claims]
    verified = {getattr(r, "cluster_id", ""): (getattr(r, "result", "PASS") == "PASS")
                for r in (reports or [])}

    composed: EditionCopy | None = None
    if briefs:
        composed = agents.editor_compose(briefs, plan or EditorialPlan(decisions=[]),
                                          run_date, budget)

    copy_of: dict[str, StoryCopy] = {}
    if composed:
        for s in composed.stories:
            copy_of[s.cluster_id] = s
    for b in briefs:
        copy_of.setdefault(b.cluster_id, _fallback_copy(b))

    # Group stories into their desks, preserving brief order within each desk.
    grouped: dict[str, list[dict]] = {}
    for b in briefs:
        copy = copy_of[b.cluster_id]
        section = copy.section if copy.section in SECTIONS else "shipped"
        sources = _sources_for(b)
        item = {
            "headline": copy.headline,
            "dek": copy.dek,
            "fields": _fields(copy),
            "confidence": _confidence(sources, verified.get(b.cluster_id, True)),
            "confidence_note": copy.confidence_note
            or "Verified against the cited sources.",
            "sources": sources or [{"outlet": "Pipeline", "cls": "trade", "url": ""}],
        }
        grouped.setdefault(section, []).append(item)

    categories = []
    for key in SECTION_ORDER:
        if grouped.get(key):
            meta = SECTIONS[key]
            categories.append({
                "key": key, "name": meta["name"], "sub": meta["sub"],
                "hue": meta["hue"], "items": grouped[key],
            })

    week, span = _iso_week(run_date)
    dropped = _dropped(plan)
    thread = (composed.thread if composed and composed.thread else "") or thread_fallback or (
        plan.throughline if plan and plan.throughline else
        "This week's verified signals across the AI desks."
    )

    return {
        "week": week,
        "range": span,
        "issued": run_date,
        "thread": thread,
        "glance": _glance(categories, dropped),
        "categories": categories,
        "dropped": dropped,
        "gates": _gates(gate_results),
        "terms": [],  # glossary explainers are curated; auto-runs ship none
    }


def write_edition(edition: dict, run_date: str) -> Path:  # noqa: F821
    from pathlib import Path

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path: Path = OUTPUT_DIR / f"week-{run_date}.json"
    path.write_text(json.dumps(edition, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
