"""Discovery, with zero API keys and zero credits.

Replaces Throughline's Tavily dependency with three open sources:

  * **RSS/Atom feeds** from arXiv and the major tech desks — free, no key, and
    higher signal per byte than a general web search for this domain.
  * **Hacker News Algolia API** — public, keyless, and its points threshold is a
    surprisingly good crowd-sourced relevance filter.
  * **ddgs** keyless search — used ONLY as a per-topic fallback when feed
    coverage on a topic is thin, so the run does not depend on it.

No model is involved at this stage. Source filtering is deterministic: deny
domains are dropped before anything downstream can see them, and reputable
domains are tagged so later stages get a hard signal instead of a guess.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import feedparser

from newsroom.config import ALLOW_DOMAINS, DENY_DOMAINS, HARVEST
from newsroom.schemas import Item

HN_ENDPOINT = "https://hn.algolia.com/api/v1/search_by_date"
_UA = "newsroom/0.1 (+local weekly AI digest)"


def domain_of(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _in(url: str, domains: frozenset[str]) -> bool:
    host = domain_of(url)
    return any(host == d or host.endswith("." + d) for d in domains)


def is_denied(url: str) -> bool:
    return _in(url, DENY_DOMAINS)


def is_reputable(url: str) -> bool:
    return _in(url, ALLOW_DOMAINS)


def _make_item(title: str, url: str, source: str, published: str, snippet: str) -> Item | None:
    title = (title or "").strip()
    url = (url or "").strip()
    if not title or not url.startswith("http") or is_denied(url):
        return None
    return Item(
        title=title,
        url=url,
        source=source,
        published=published,
        snippet=" ".join((snippet or "").split())[:400],
        domain=domain_of(url),
        quality="reputable" if is_reputable(url) else "unverified",
    )


def _recent(entry, cutoff: datetime) -> bool:
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not parsed:
        return True  # undated: keep, let clustering sort it out
    try:
        return datetime.fromtimestamp(time.mktime(parsed), tz=UTC) >= cutoff
    except (ValueError, OverflowError):
        return True


def from_feeds(cutoff: datetime) -> list[Item]:
    items: list[Item] = []
    for url in HARVEST["feeds"]:
        try:
            feed = feedparser.parse(url)
        except Exception:
            continue
        source = getattr(feed.feed, "title", domain_of(url))
        for entry in getattr(feed, "entries", [])[:40]:
            if not _recent(entry, cutoff):
                continue
            item = _make_item(
                getattr(entry, "title", ""),
                getattr(entry, "link", ""),
                source,
                getattr(entry, "published", ""),
                getattr(entry, "summary", ""),
            )
            if item:
                items.append(item)
    return items


def from_hackernews(cutoff: datetime) -> list[Item]:
    """Public Algolia endpoint. Points act as a crowd relevance filter."""
    since = int(cutoff.timestamp())
    min_points = int(HARVEST["hn_min_points"])
    query = (
        f"{HN_ENDPOINT}?tags=story&numericFilters=created_at_i>{since},"
        f"points>{min_points}&hitsPerPage=60&query=AI"
    )
    try:
        import json

        req = Request(query, headers={"User-Agent": _UA})
        with urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []

    items: list[Item] = []
    for hit in payload.get("hits", []):
        url = hit.get("url") or ""
        if not url:
            continue
        item = _make_item(
            hit.get("title", ""),
            url,
            f"Hacker News ({hit.get('points', 0)} pts)",
            hit.get("created_at", ""),
            hit.get("story_text", "") or "",
        )
        if item:
            items.append(item)
    return items


def search_topic(query: str, max_results: int = 8) -> list[Item]:
    """Keyless per-topic search. Fallback only — never the primary source."""
    if not HARVEST.get("search_fallback", True):
        return []
    try:
        from ddgs import DDGS
    except ImportError:
        return []

    items: list[Item] = []
    try:
        with DDGS() as ddgs:
            for hit in ddgs.news(query, max_results=max_results) or []:
                item = _make_item(
                    hit.get("title", ""),
                    hit.get("url", "") or hit.get("href", ""),
                    hit.get("source", ""),
                    hit.get("date", ""),
                    hit.get("body", "") or hit.get("excerpt", ""),
                )
                if item:
                    items.append(item)
    except Exception:
        return items
    return items


def dedupe(items: list[Item]) -> list[Item]:
    """Exact-URL dedup, preferring the reputable copy of a syndicated story."""
    best: dict[str, Item] = {}
    for item in items:
        key = item.url.rstrip("/")
        current = best.get(key)
        if current is None or (item.quality == "reputable" and current.quality != "reputable"):
            best[key] = item
    return list(best.values())


def harvest() -> list[Item]:
    """The full sweep. Deterministic: same inputs, same output, no model."""
    cutoff = datetime.now(UTC) - timedelta(days=int(HARVEST["lookback_days"]))
    items = dedupe(from_feeds(cutoff) + from_hackernews(cutoff))
    # Reputable first, so a max_items truncation cuts the tail, not the good stuff.
    items.sort(key=lambda i: (i.quality != "reputable", i.title.lower()))
    return items[: int(HARVEST["max_items"])]
