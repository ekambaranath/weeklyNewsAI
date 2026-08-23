"""Deterministic citation numbering.

Numbering is a bijection, and models are bad at bijections — they drift into
per-section local numbering while the Sources list stays global, so markers
dangle and sources orphan. Small local models are worse at it than frontier
models, so this matters more here than it did in the original.

Contract: the editor cites by wrapping the URL in double brackets right after
the claim — ``[[https://example.com/x]]``. This module assigns global 1..N by
first appearance and rebuilds the Sources list, guaranteeing the 1:1 property
that ``gates.citation_integrity`` then verifies.
"""

from __future__ import annotations

import re

_MARKER = re.compile(r"\[\[\s*(https?://[^\]\s]+?)\s*\]\]")
_URL = re.compile(r"https?://[^\s)\]>]+")
_LEAD = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+")
_SPLIT = re.compile(r"^(##\s+Sources\b.*)$", re.MULTILINE)


def _norm(url: str) -> str:
    url = url.strip().rstrip(".,);]")
    return url[:-1] if url.endswith("/") else url


def renumber(report: str, meta: dict[str, str] | None = None) -> tuple[str, list[str]]:
    """Return (renumbered_report, warnings).

    ``meta`` maps URL -> display line, so a Sources entry can be reconstructed
    even when the model forgot to list it.
    """
    parts = _SPLIT.split(report, maxsplit=1)
    body, heading, block = (parts[0], parts[1], parts[2]) if len(parts) >= 3 else (report, "", "")

    order: list[str] = []
    number: dict[str, int] = {}
    for match in _MARKER.finditer(body):
        url = _norm(match.group(1))
        if url not in number:
            number[url] = len(order) + 1
            order.append(url)

    if not order:
        return report, ["no [[url]] markers found — report left unchanged"]

    new_body = _MARKER.sub(lambda m: f"[{number[_norm(m.group(1))]}]", body)

    listed: dict[str, str] = dict(meta or {})
    for line in block.splitlines():
        found = _URL.search(line)
        if found:
            listed[_norm(found.group(0))] = _LEAD.sub("", line).strip()

    warnings: list[str] = []
    lines = []
    for n, url in enumerate(order, start=1):
        text = listed.get(url)
        if text is None:
            text = url
            warnings.append(f"cited URL missing from Sources, reconstructed: {url}")
        lines.append(f"{n}. {text}")

    orphans = sorted(set(listed) - set(order))
    if orphans:
        warnings.append(f"dropped {len(orphans)} uncited source(s)")

    if not heading:
        warnings.append("no '## Sources' section — appended")
        heading = "## Sources"
        rebuilt = new_body.rstrip() + "\n\n" + heading + "\n\n" + "\n".join(lines) + "\n"
    else:
        rebuilt = new_body + heading + "\n\n" + "\n".join(lines) + "\n"

    return rebuilt, warnings
