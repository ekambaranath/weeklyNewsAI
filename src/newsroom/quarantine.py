"""Evidence quarantine — written by code, never by a model.

This is the single most important fix to the Throughline design.

Throughline instructs its researchers to write the *complete, verbatim* output
of every search into a file, then has a verifier check claims against that file.
Two problems:

  1. **Cost.** The raw text passes through the model as OUTPUT tokens — the most
     expensive kind — purely to persist text the tool already returned.
  2. **Correctness, and this one matters more.** Language models do not copy
     verbatim. They compress, normalise and drop qualifiers. So the "quarantined
     sources" the verifier grades against are themselves a lossy model artifact.
     The verifier is checking the researcher's homework against the researcher's
     own transcription. A silently reworded quote certifies as SUPPORTED.

Here the harvest layer writes the evidence directly to disk and hands the model
only a compact digest with stable chunk IDs. The chain of custody from source to
verification never passes through a model, so the evidence is exactly what the
publisher published.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from newsroom.config import QUARANTINE_DIR
from newsroom.schemas import Item

_SLUG = re.compile(r"[^a-z0-9]+")


def slug(topic: str) -> str:
    return _SLUG.sub("-", topic.lower()).strip("-")[:60] or "topic"


def topic_dir(topic: str) -> Path:
    path = QUARANTINE_DIR / slug(topic)
    path.mkdir(parents=True, exist_ok=True)
    return path


def store(topic: str, items: list[Item]) -> list[dict]:
    """Persist evidence and return the digest the model is allowed to see.

    Writes ``evidence.jsonl`` (full records, append-only) and returns one small
    dict per item: chunk id, title, domain, quality tag, and a short snippet.
    The model sees roughly 60 tokens per source instead of 600.
    """
    path = topic_dir(topic)
    evidence_path = path / "evidence.jsonl"

    existing: dict[str, dict] = {}
    if evidence_path.is_file():
        for line in evidence_path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
                existing[record["url"]] = record
            except (json.JSONDecodeError, KeyError):
                continue

    for index, item in enumerate(items):
        if item.url in existing:
            continue
        existing[item.url] = {
            "chunk_id": f"{slug(topic)}-{len(existing) + index:03d}",
            "url": item.url,
            "title": item.title,
            "source": item.source,
            "domain": item.domain,
            "quality": item.quality,
            "published": item.published,
            "text": item.snippet,
        }

    with open(evidence_path, "w", encoding="utf-8") as fh:
        for record in existing.values():
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    return [
        {
            "chunk_id": r["chunk_id"],
            "title": r["title"],
            "url": r["url"],
            "domain": r["domain"],
            "quality": r["quality"],
            "snippet": r["text"][:220],
        }
        for r in existing.values()
    ]


def load(topic: str) -> list[dict]:
    path = topic_dir(topic) / "evidence.jsonl"
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def evidence_for(topic: str, url: str) -> dict | None:
    """Keyed lookup of the exact source backing a claim.

    Verification does not need retrieval. Every claim carries the URL it cites,
    so the verifier is handed that one record — not the whole 20k-token dump the
    original design fed it. Cheaper, and far more accurate: needle-in-haystack
    accuracy collapses on long concatenated evidence, especially on small models.
    """
    target = url.rstrip("/")
    for record in load(topic):
        if record["url"].rstrip("/") == target:
            return record
    return None


def digest(topic: str, limit: int = 12) -> list[dict]:
    return [
        {
            "chunk_id": r["chunk_id"],
            "title": r["title"],
            "url": r["url"],
            "quality": r["quality"],
            "snippet": r["text"][:220],
        }
        for r in load(topic)[:limit]
    ]
