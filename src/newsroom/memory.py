"""Cross-run memory.

Two halves, deliberately split by what each is good at:

  * ``centroids.json`` (in cluster.py) — the machine-readable half. Similarity
    against past runs, used to LABEL continuity.
  * ``coverage.md`` + ``last-run.json`` (here) — the human-readable half. A
    one-line synopsis per topic, so a DEVELOPING assignment can be framed as
    "here is what we said last time; report the delta."

The original stores continuity only as prose and asks the model to recall it.
Prose is the right medium for briefing the writer, and the wrong medium for
deciding whether two stories are the same story. Doing both means the editor
never has to do arithmetic on a ledger.
"""

from __future__ import annotations

import json
from datetime import date

from newsroom.config import MEMORY_DIR
from newsroom.schemas import Brief, EditorialPlan, MemoryEntry

COVERAGE_PATH = MEMORY_DIR / "coverage.md"
LAST_RUN_PATH = MEMORY_DIR / "last-run.json"
KEEP_RUNS = 8


def prior_summaries() -> dict[str, str]:
    """Topic -> last synopsis, for framing DEVELOPING assignments."""
    if not LAST_RUN_PATH.is_file():
        return {}
    try:
        payload = json.loads(LAST_RUN_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {e["topic"]: e.get("synopsis", "") for e in payload.get("entries", [])}


def coverage_text() -> str:
    if COVERAGE_PATH.is_file():
        return COVERAGE_PATH.read_text(encoding="utf-8")
    return "# Coverage ledger\n\nNo prior runs — treat everything as NEW.\n"


def write(briefs: list[Brief], plan: EditorialPlan, run_date: str | None = None) -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    run_date = run_date or date.today().isoformat()
    status_of = {d.cluster_id: d.status for d in plan.decisions}

    entries = [
        MemoryEntry(
            topic=b.topic,
            status=status_of.get(b.cluster_id, "NEW"),
            synopsis=(b.claims[0].text if b.claims else b.reason)[:220],
            sources=sorted({c.source_url for c in b.claims}),
        )
        for b in briefs
    ]

    LAST_RUN_PATH.write_text(
        json.dumps(
            {"run": run_date, "entries": [e.model_dump() for e in entries]},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    block = [f"## Run of {run_date}"]
    block += [f"- {e.topic} [{e.status}] — {e.synopsis}" for e in entries] or ["- (nothing kept)"]

    existing = coverage_text() if COVERAGE_PATH.is_file() else "# Coverage ledger\n"
    sections = existing.split("\n## ")
    header, past = sections[0], ["## " + s for s in sections[1:]]
    past = past[-(KEEP_RUNS - 1) :]  # bounded: the ledger cannot grow forever

    COVERAGE_PATH.write_text(
        header.rstrip() + "\n\n" + "\n\n".join(past + ["\n".join(block)]).strip() + "\n",
        encoding="utf-8",
    )
