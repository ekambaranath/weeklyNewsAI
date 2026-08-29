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


def model_check() -> int:
    """Prove the model backend actually answers, and say why if it does not."""
    from newsroom.config import MODELS
    from newsroom.models import BACKEND, check

    _banner("MODEL CHECK")
    print(f"  backend: {BACKEND}")
    print(f"  strong:  {MODELS.get('strong' if BACKEND == 'openrouter' else 'ollama_strong', MODELS['strong'])}")
    ok, detail = check()
    if ok:
        print(f"\n  ✓ live call succeeded — reply: {detail!r}")
        return 0
    print(f"\n  ✗ live call FAILED\n  {detail}")
    if BACKEND == "openrouter":
        print(
            "\n  Common causes on OpenRouter's free tier:\n"
            "   • the key is wrong or was pasted with a trailing newline\n"
            "   • the account's Privacy setting blocks free models — enable\n"
            "     'Model training / prompt logging' at openrouter.ai/settings/privacy\n"
            "   • the model id is unavailable; try another free model in config.toml\n"
            "   • daily free-tier rate limit reached — wait, or add a small credit"
        )
        from newsroom.models import list_free_models

        print("\n  Free NVIDIA / Nemotron models OpenRouter serves right now:")
        nvidia = [m for m in list_free_models("nemotron")] + [
            m for m in list_free_models("nvidia/") if "nemotron" not in m.lower()
        ]
        for m in nvidia or ["   (none found matching nvidia/nemotron)"]:
            print(f"     {m}")
        others = [m for m in list_free_models() if "nvidia" not in m.lower()][:12]
        if others:
            print("\n  Other free models available (sample):")
            for m in others:
                print(f"     {m}")
        print("\n  Put a valid slug in config.toml [models] strong/mid/small.")
    return 1


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

    from newsroom.models import BACKEND

    _banner(f"NEWSROOM — {run_date}")
    print("  Tier 0 orchestrator: deterministic")
    if BACKEND == "openrouter":
        print("  Tier 1-3 agents:     OpenRouter (hosted), free tier\n")
    else:
        print("  Tier 1-3 agents:     local (Ollama), $0.00 API cost\n")

    # Stream both modes: "updates" for per-node progress, "values" for the full
    # merged state after each step. The last "values" snapshot is authoritative —
    # unlike accumulating "updates" deltas, it has the reducer-merged briefs and
    # reports the edition compose step depends on.
    result: dict = {}
    best_briefs: list = []  # richest briefs-with-claims seen in ANY snapshot
    for mode, chunk in graph.stream(state, stream_mode=["updates", "values"]):
        if mode == "updates":
            for node in chunk or {}:
                print(f"  → {node}", flush=True)
        elif chunk:
            result = chunk
            snap = [b for b in chunk.get("briefs", []) if getattr(b, "claims", None)]
            # Verification/pruning can thin briefs late; keep the fullest set we saw
            # so a strict late gate can't erase an otherwise shippable edition.
            if len(snap) > len(best_briefs):
                best_briefs = snap

    report = result.get("report", "")
    all_briefs = result.get("briefs", [])
    briefs = best_briefs or [b for b in all_briefs if getattr(b, "claims", None)]
    plan = result.get("plan")

    for warning in result.get("warnings", []) or []:
        print(f"  ⚠ {warning}")

    print(
        f"  [diag] state keys={sorted(result)} | briefs={len(all_briefs)} "
        f"with_claims={len(briefs)} "
        f"claimcounts={[len(getattr(b, 'claims', [])) for b in all_briefs]}"
    )

    # The edition JSON — not the markdown — is what every deliverable consumes, and
    # it is composed from the verified BRIEFS, independent of the markdown synthesis
    # call. So a flaky synthesis (a transient upstream 502, say) must not lose the
    # run: as long as briefs survived, we can still build and ship an edition.
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    latest = OUTPUT_DIR / "report.md"
    archived = REPORTS_DIR / f"{run_date}.md"
    if report.strip():
        latest.write_text(report, encoding="utf-8")
        archived.write_text(report, encoding="utf-8")
        _banner("QUALITY GATES")
        print(format_gates(result.get("gate_results", [])))
    else:
        print("  ⚠ markdown synthesis produced nothing; building edition from briefs")

    # Compose the edition JSON that every deliverable consumes. The markdown is
    # the intermediate artifact; this document, and the PDF rendered from it, are
    # what actually ships. Built from THIS run's verified briefs, so it is fresh.
    from newsroom.edition import build_edition, write_edition

    run_json = OUTPUT_DIR / f"week-{run_date}.json"
    edition = None
    if briefs:
        try:
            edition = build_edition(
                briefs,
                plan,
                result.get("reports", []),
                result.get("gate_results", []),
                run_date,
                state["budget"],
                thread_fallback=report.split("\n\n", 2)[1] if "\n\n" in report else "",
            )
            run_json = write_edition(edition, run_date)
            signals = sum(len(c["items"]) for c in edition["categories"])
            print(f"\n  Edition:    {run_json}  ({signals} signals, "
                  f"{len(edition['categories'])} desks)")
        except Exception as exc:  # composing must never lose a completed run
            print(f"  \u26a0 Edition compose failed ({exc})")

    # Fail only when there is genuinely nothing to ship. Name the real cause so an
    # overloaded free endpoint or a bad model id is distinguishable from quiet news.
    if edition is None or not edition.get("categories"):
        print("\nNo edition produced \u2014 nothing survived verification.")
        from newsroom.models import LAST_ERROR

        if LAST_ERROR:
            print(f"\n  Last model error: {LAST_ERROR}")
            print("  A 5xx / 'overloaded' error means the free model was busy \u2014 retry.")
            print("  Otherwise run:  python -m newsroom.run --check")
        print(state["budget"].report())
        return 1

    # The PDF briefing is the email attachment, so render it from the fresh JSON.
    pdf_path = None
    if run_json.is_file():
        try:
            from newsroom.render import render_pdf

            pdf_path = render_pdf(run_json)
        except Exception as exc:  # rendering must never lose a completed run
            print(f"  \u26a0 PDF render failed ({exc}); markdown retained")

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
    parser.add_argument("--preflight", action="store_true", help="check no addresses can reach the repo")
    parser.add_argument("--check", action="store_true", help="make one live model call and report the result")
    args = parser.parse_args()

    if args.check:
        return model_check()
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
    if args.preflight:
        from newsroom.deliver import preflight

        print("  Privacy preflight:")
        issues = preflight(verbose=True)
        if issues:
            print("PRIVACY CHECK FAILED\n")
            for i in issues:
                print(f"  ! {i}")
            return 2
        print("  PRIVACY CHECK PASSED — no recipient address is tracked or in history")
        return 0
    if args.cron:
        from newsroom.deliver import cron_line

        print(cron_line())
        return 0
    if args.send or args.dry_send:
        from newsroom.deliver import send

        run_json = Path(args.send or args.dry_send)
        stamp = run_json.stem.replace("week-", "")
        name = f"briefing-{stamp}.pdf"
        # Look beside the run file first, then in output/. The PDF is the point
        # of the email, so a missing one is fatal rather than a silent omission.
        candidates = [run_json.parent / name, OUTPUT_DIR / name]
        pdf = next((c for c in candidates if c.is_file()), None)
        if pdf is None:
            print(f"  No {name} found. Looked in:")
            for c in candidates:
                print(f"    {c}")
            print("  Render it first:  python -m newsroom.run --pdf "
                  f"{run_json}")
            return 2
        print(f"  Attaching:  {pdf}")
        return send(run_json, pdf_path=pdf, dry_run=bool(args.dry_send))
    return full_run()


if __name__ == "__main__":
    sys.exit(main())
