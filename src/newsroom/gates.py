"""Deterministic quality gates — free, and run INLINE.

Throughline has these five checks, but only as an offline eval suite scored
against a frozen dataset. That is a waste of a good asset: they are pure
functions costing nothing, and they catch mechanical defects far more reliably
than asking a model to proofread prose.

Here they are promoted to runtime publish gates. The expensive LLM reviewer is
only dispatched when a gate fails, so a clean run skips it entirely. Same
functions still serve as the offline regression suite — which is what lets you
say "9x cheaper with measured zero regression" rather than "it seems fine".

Also includes the entity/number fidelity check. Throughline's verifier *prompt*
asks the model to confirm that "every model name, product name, organisation,
person and quantity appears in the source material". That is set membership, not
inference. Doing it in code is both free and strictly more reliable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from newsroom.config import GATES, HYPE_TERMS, SENSITIVE_TERMS
from newsroom.harvest import is_reputable

_URL = re.compile(r"https?://[^\s)\]>]+")
_MARKER = re.compile(r"\[(\d+)\]")
_PROPER = re.compile(r"\b([A-Z][a-zA-Z0-9\-\.]*(?:\s+[A-Z][a-zA-Z0-9\-\.]*)*)\b")
_NUMBER = re.compile(r"\b\d[\d,\.]*\s?(?:%|x|bn|b|m|k|billion|million|trillion)?\b", re.I)
_SENT = re.compile(r"(?<=[.!?])\s+")

# Words that start sentences or head sections and are not entity claims.
_PROPER_STOPWORDS = {
    "The", "A", "An", "This", "That", "These", "Those", "It", "In", "On", "At",
    "For", "But", "And", "Since", "While", "After", "Before", "However",
    "Meanwhile", "Sources", "Throughline", "New", "Developing", "Week", "AI",
}


@dataclass
class GateResult:
    name: str
    passed: bool
    score: float
    detail: str


def _body(report: str) -> str:
    return re.split(r"^##\s+Sources\b", report, maxsplit=1, flags=re.M)[0]


def _sources_block(report: str) -> str:
    parts = re.split(r"^##\s+Sources\b", report, maxsplit=1, flags=re.M)
    return parts[1] if len(parts) > 1 else ""


def source_quality(report: str) -> GateResult:
    urls = {u.rstrip(".,);]") for u in _URL.findall(_sources_block(report))}
    if not urls:
        return GateResult("source_quality", False, 0.0, "no sources listed")
    good = [u for u in urls if is_reputable(u)]
    ratio = len(good) / len(urls)
    minimum = float(GATES["min_reputable_ratio"])
    return GateResult(
        "source_quality",
        ratio >= minimum,
        round(ratio, 3),
        f"{len(good)}/{len(urls)} reputable (need {minimum:.0%})",
    )


def source_count(report: str) -> GateResult:
    urls = {u.rstrip(".,);]") for u in _URL.findall(_sources_block(report))}
    minimum = int(GATES["min_distinct_sources"])
    return GateResult(
        "source_count",
        len(urls) >= minimum,
        float(len(urls)),
        f"{len(urls)} distinct sources (need {minimum})",
    )


def citation_integrity(report: str) -> GateResult:
    """Every marker resolves to a source; every source is cited. Exactly 1:1."""
    body, sources = _body(report), _sources_block(report)
    used = {int(n) for n in _MARKER.findall(body)}
    listed = {
        int(m.group(1))
        for line in sources.splitlines()
        if (m := re.match(r"\s*(\d+)[.)]", line))
    }
    problems = []
    dangling = used - listed
    orphans = listed - used
    if dangling:
        problems.append(f"markers with no source: {sorted(dangling)}")
    if orphans:
        problems.append(f"sources never cited: {sorted(orphans)}")
    if listed and listed != set(range(1, max(listed) + 1)):
        problems.append("source numbering is not a contiguous 1..N sequence")
    universe = len(used | listed) or 1
    score = max(0.0, 1.0 - len(dangling | orphans) / universe)
    return GateResult(
        "citation_integrity",
        not problems,
        round(score, 3),
        "; ".join(problems) or "1:1 marker/source correspondence",
    )


# The report format invites one advisory sentence per section — "what this means
# for someone building with AI". That is editorial interpretation, not a factual
# assertion, and demanding a citation on it would fail every clean report and
# fire the expensive LLM reviewer on every run. Advisory sentences are scored
# separately rather than counted as ungrounded claims.
_ADVISORY = re.compile(
    r"\b(should|worth|means (?:that )?|if you|for (?:anyone|teams|those)|"
    r"expect to|consider|likely to matter|the practical|in practice, )",
    re.I,
)


def _sentences(text: str) -> list[str]:
    """Split on both sentence punctuation and line breaks; drop headings."""
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(">"):
            continue
        out.extend(s.strip() for s in _SENT.split(line) if s.strip())
    return out


def _sections_only(body: str) -> str:
    """Everything from the first ``##`` section onward.

    The lede is a synthesis of material the sections below already cite;
    requiring its own markers would double-cite the whole report and fail every
    clean run.
    """
    match = re.search(r"^##\s+", body, flags=re.M)
    return body[match.start() :] if match else body


def groundedness(report: str) -> GateResult:
    """Share of factual sentences carrying a citation marker."""
    sentences = [s for s in _sentences(_sections_only(_body(report))) if len(s.split()) >= 6]
    factual = [s for s in sentences if not _ADVISORY.search(s)]
    advisory = len(sentences) - len(factual)

    if not factual:
        return GateResult("groundedness", False, 0.0, "no factual sentences found")

    cited = [s for s in factual if _MARKER.search(s)]
    ratio = len(cited) / len(factual)
    minimum = float(GATES["min_groundedness"])
    uncited = [s[:60] for s in factual if not _MARKER.search(s)][:3]
    return GateResult(
        "groundedness",
        ratio >= minimum,
        round(ratio, 3),
        f"{len(cited)}/{len(factual)} factual sentences cited"
        + f" ({advisory} advisory exempt)"
        + (f"; uncited e.g. {uncited}" if uncited else ""),
    )


def voice(report: str) -> GateResult:
    body = _body(report).lower()
    words = max(len(body.split()), 1)
    hits = sum(body.count(term) for term in HYPE_TERMS)
    density = hits / words * 100
    ceiling = float(GATES["max_hype_per_100w"])
    return GateResult(
        "voice",
        density <= ceiling,
        round(density, 3),
        f"{hits} hype term(s), {density:.2f} per 100 words (ceiling {ceiling})",
    )


def entity_fidelity(claim: str, evidence_text: str) -> tuple[bool, list[str]]:
    """Do the claim's proper nouns and numbers appear in its cited source?

    Pure string work. Catches the exact failure mode Throughline's verifier
    prompt describes — an invented model name, a misremembered figure — without
    spending a single token, and without a small local model's judgement.
    """
    haystack = evidence_text.lower()
    missing: list[str] = []

    for match in _PROPER.finditer(claim):
        term = match.group(1).strip()
        head = term.split()[0]
        if head in _PROPER_STOPWORDS or len(term) < 3:
            continue
        if term.lower() not in haystack:
            # Allow a partial match on multi-word names (outlet style varies).
            parts = [p for p in term.split() if len(p) > 3]
            if parts and any(p.lower() in haystack for p in parts):
                continue
            missing.append(term)

    for match in _NUMBER.finditer(claim):
        token = match.group(0).strip().lower()
        if len(token) < 2 or token.rstrip("%xkmb.,").isdigit() and len(token) < 3:
            continue
        bare = token.rstrip("%xkmb ").replace(",", "")
        if token not in haystack and bare and bare not in haystack.replace(",", ""):
            missing.append(token)

    return (not missing), missing[:6]


def sensitive_flags(report: str) -> list[str]:
    lower = report.lower()
    return sorted(t for t in SENSITIVE_TERMS if t in lower)


ALL_GATES = (source_count, source_quality, citation_integrity, groundedness, voice)


def run_gates(report: str) -> tuple[bool, list[GateResult]]:
    results = [gate(report) for gate in ALL_GATES]
    return all(r.passed for r in results), results


def format_gates(results: list[GateResult]) -> str:
    return "\n".join(
        f"  {'PASS' if r.passed else 'FAIL'}  {r.name:<20} {r.score:<7} {r.detail}"
        for r in results
    )
