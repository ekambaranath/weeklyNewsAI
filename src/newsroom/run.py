"""Run the newsroom.

    python -m newsroom.run                 # full run
    python -m newsroom.run --dry-run       # harvest + cluster only, no LLM calls
    python -m newsroom.run --gates-only <file.md>   # score an existing report

The dry run matters: it exercises the entire deterministic half of the pipeline
— harvesting, filtering, clustering, continuity labelling — without loading a
model. That is where most bugs live, and it iterates in seconds.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from newsroom import cluster as clustering
from newsroom import harvest, memory
from newsroom.config import OUTPUT_DIR, QUARANTINE_DIR, REPORTS_DIR
from newsroom.gates import format_gates, run_gates


def _banner(text: str) -> None:
    print(f"\n{'─' * 62}\n{text}\n{'─' * 62}", flush=True)


def dry_run() -> int:
    _banner("DRY RUN — deterministic pipeline only, no model loaded")
    items = harvest.harvest()
    print(f"Harvested {len(items)} items")
    reputable = sum(1 for i in items if i.quality == "reputable")
    print(f"  reputable: {reputable}   unverified: {len(items) - reputable}")
    if not items:
        print("\nNothing harvested. Check network access to the feed hosts.")
        return 1

    clusters = clustering.label_continuity(clustering.build_clusters(items))
    print(f"\nClustered into {len(clusters)} candidate topics:\n")
    for c in clusters[:12]:
        rep = sum(1 for i in c.items if i.quality == "reputable")
        prior = f" ~{c.prior_similarity} vs '{c.prior_topic}'" if c.prior_topic else ""
        print(f"  [{c.suggested_status:<10}] {c.label[:44]:<46} {len(c.items):>2} items, {rep} reputable{prior}")
        for item in c.exemplars(2):
            print(f"      · {item.title[:70]}")
    return 0


def gates_only(path: str) -> int:
    report = Path(path).read_text(encoding="utf-8")
    passed, results = run_gates(report)
    _banner(f"GATE REPORT — {path}")
    print(format_gates(results))
    print(f"\n  OVERALL: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


def full_run() -> int:
    from newsroom.graph import build_graph, initial_state

    run_date = date.today().isoformat()
    graph = build_graph()
    state = initial_state(run_date)

    _banner(f"NEWSROOM — {run_date}")
    print("  Tier 0 orchestrator: deterministic")
    print("  Tier 1-3 agents:     local (Ollama), $0.00 API cost\n")

    final: dict = {}
    for chunk in graph.stream(state, stream_mode="updates"):
        for node, update in chunk.items():
            final.update({k: v for k, v in (update or {}).items()})
            print(f"  → {node}", flush=True)

    result = graph.invoke(state) if not final else final
    report = result.get("report", "")

    for warning in result.get("warnings", []) or []:
        print(f"  ⚠ {warning}")

    if not report.strip():
        print("\nNo report produced. Nothing survived verification.")
        print(state["budget"].report())
        return 1

    _banner("QUALITY GATES")
    print(format_gates(result.get("gate_results", [])))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    latest = OUTPUT_DIR / "report.md"
    archived = REPORTS_DIR / f"{run_date}.md"
    latest.write_text(report, encoding="utf-8")
    archived.write_text(report, encoding="utf-8")

    # Markdown is the intermediate artifact; the PDF briefing is the deliverable.
    pdf_path = None
    run_json = OUTPUT_DIR / f"week-{run_date}.json"
    if run_json.is_file():
        try:
            from newsroom.render import render_pdf

            pdf_path = render_pdf(run_json)
        except Exception as exc:  # rendering must never lose a completed run
            print(f"  \u26a0 PDF render failed ({exc}); markdown retained")

    briefs = result.get("briefs", [])
    plan = result.get("plan")
    if briefs and plan:
        memory.write(briefs, plan, run_date)
        clusters = result.get("clusters", [])
        topics = {b.cluster_id: b.topic for b in briefs}
        clustering.record_run(
            [c for c in clusters if c.cluster_id in topics], topics, run_date
        )

    _banner("BUDGET")
    print(state["budget"].report())

    if pdf_path:
        print(f"\n  Briefing:   {pdf_path}")
    print(f"  Report:     {latest}")
    print(f"  Archive:    {archived}")
    print(f"  Evidence:   {QUARANTINE_DIR}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Local, zero-cost AI news agent.")
    parser.add_argument("--dry-run", action="store_true", help="deterministic pipeline only")
    parser.add_argument("--gates-only", metavar="FILE", help="score an existing report")
    parser.add_argument("--pdf", metavar="JSON", help="render the print PDF from a run file")
    parser.add_argument("--web", metavar="JSON", help="render the animated web edition")
    parser.add_argument("--email-preview", metavar="JSON", help="render the email edition to a file")
    parser.add_argument("--send", metavar="JSON", help="email the edition to configured recipients")
    parser.add_argument("--dry-send", metavar="JSON", help="show who would receive it, send nothing")
    parser.add_argument("--cron", action="store_true", help="print the crontab line for the schedule")
    args = parser.parse_args()

    if args.dry_run:
        return dry_run()
    if args.gates_only:
        return gates_only(args.gates_only)
    if args.pdf:
        from newsroom.render import render_pdf

        print(f"  Print PDF:  {render_pdf(args.pdf)}")
        return 0
    if args.web:
        from newsroom.newspaper import render_web

        print(f"  Web:        {render_web(args.web)}")
        return 0
    if args.email_preview:
        from newsroom.deliver import load_config
        from newsroom.email_edition import render_email

        try:
            url = load_config().get("web_url", "")
        except RuntimeError:
            url = ""
        print(f"  Email:      {render_email(args.email_preview, url)}")
        return 0
    if args.cron:
        from newsroom.deliver import cron_line

        print(cron_line())
        return 0
    if args.send or args.dry_send:
        from newsroom.deliver import send

        run_json = args.send or args.dry_send
        pdf = OUTPUT_DIR / f"briefing-{Path(run_json).stem.replace('week-', '')}.pdf"
        return send(run_json, pdf_path=pdf, dry_run=bool(args.dry_send))
    return full_run()


if __name__ == "__main__":
    sys.exit(main())
