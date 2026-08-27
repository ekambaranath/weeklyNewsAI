# This Week in AI

A weekly AI newspaper, assembled and delivered by a hierarchy of agents. Every
edition is **regenerated from that week's live feeds** and mailed to its
recipients — no static copy, no hand-editing. It runs two ways, both free:

- **Local** — three Ollama models. No API keys, no credits, `$0.00 per run`.
- **Hosted** — the same tiers on OpenRouter's free tier. This is what lets the
  edition **rebuild itself unattended in GitHub Actions**, which has no GPU to
  host Ollama. One free key (`$OPENROUTER_API_KEY`), still `$0.00` — rate-limited
  rather than billed.

Flip between them with a single line in `config.toml` (`[models] backend`);
nothing else changes.

## Three editions, one source

| Edition | Format | Carries |
|---|---|---|
| **Web** | self-contained `.html` | animated jargon explainers, full charts, every source linked |
| **Email** | table-based multipart | the thread, four numbers, each headline with its confidence grade — the trailer |
| **Print** | A4 `.pdf` | the archive copy; animations degrade to their static first frame |

Email is a separate build, not a squeezed copy of the web one: Outlook renders
with Word's engine, nobody runs JavaScript, and web fonts are unreliable. So it
is nested tables, inline styles, system fonts, and a `text/plain` alternative —
which several providers require to stay out of spam.

## Explaining the jargon

Terms are marked inline and explained in a keyed sidebar next to the story that
uses them — the newspaper convention, with a moving diagram instead of a
paragraph. Animation is used only where the concept **is** a process: three
conditions converging into a lethal trifecta, a hidden instruction riding inside
fetched content, a capability gauge climbing into its red band. `CVSS` is a
number on a scale, so it gets no animation.

Each explainer is inline SVG with CSS keyframes — no JavaScript, no external
requests, `prefers-reduced-motion` respected, and it degrades to a static first
frame in the PDF.

A rebuild of the [Throughline](https://github.com/joel-langchain/throughline)
architecture, with two changes that matter: the evidence chain of custody never
passes through a model, and orchestration lives in graph edges rather than in a
system prompt.

---

## The hierarchy

```
Tier 0   ORCHESTRATOR                                    deterministic, no LLM
         routing · fan-out · retry caps · budget · quality gates
             │
Tier 1   MANAGING EDITOR                                 strong local model
         2 calls per run: what matters, and the finished prose
             │
Tier 2   LEADS                                           mid local model
         ├─ Research Lead        allocates depth unevenly, on purpose
         ├─ Verification Lead    adjudicates only escalated claims
         └─ Publishing Lead      decides whether review is even needed
             │
Tier 3   WORKERS                                         small local model
         ├─ topic-researcher ×N  parallel, isolated context per topic
         ├─ claim-verifier ×N    one claim, one source, no web access
         └─ final-pass-reviewer  conditional — fires only when a gate fails
```

**The rule that keeps a hierarchy from becoming overhead: a tier exists only
where judgement is required.** Routing, retry counting, dedup, citation
numbering and quality gating are not judgement. They live in Tier 0 as plain
functions, so the managers manage instead of clerk.

---

## Setup

```bash
pip install -e .
```

Then pick a backend in `config.toml` under `[models]`:

**Hosted (default — runs in CI):**
```toml
[models]
backend = "openrouter"
```
```bash
export OPENROUTER_API_KEY=sk-or-...     # free key: https://openrouter.ai/keys
```

**Local ($0, no key):**
```toml
[models]
backend = "ollama"
```
```bash
ollama pull qwen2.5:14b-instruct     # Tier 1 editor
ollama pull qwen2.5:7b-instruct      # Tier 2 leads
ollama pull llama3.2:3b              # Tier 3 workers
```

Smaller machine? Drop each tier one notch in `config.toml` — the graph does not
care which models sit behind the tiers.

### Weekly automation (GitHub Actions)

`.github/workflows/weekly-send.yml` regenerates and mails the edition every
Monday. Add three repository secrets (Settings → Secrets and variables →
Actions):

| Secret | What it is |
|---|---|
| `OPENROUTER_API_KEY` | your free OpenRouter key — the models the pipeline runs on |
| `RECIPIENTS_TOML` | the full contents of your `recipients.toml` (kept out of git) |
| `NEWSROOM_SMTP_PASSWORD` | the sending mailbox's app password |

Trigger it by hand first (Actions → *Weekly edition* → Run workflow) with
**dry_run** left on: it builds the edition and lists who *would* receive it
without sending. Turn dry_run off, or wait for Monday, to send for real.

## Run

```bash
python -m newsroom.run --dry-run              # deterministic half only, no model
python -m newsroom.run                        # full run: harvest → compose → PDF
python -m newsroom.run --send output/week-<date>.json   # mail the built edition
python -m newsroom.run --gates-only report.md # score an existing report
```

**Start with `--dry-run`.** It exercises harvesting, filtering, clustering and
continuity labelling without loading a model, in seconds. Most bugs live there.

A full run harvests the week's feeds, researches and verifies each topic, and
**composes `output/week-<date>.json`** — the edition every deliverable is built
from — then renders the PDF briefing. It also writes `output/report.md`, a dated
copy in `output/reports/`, evidence in `output/research/<topic>/evidence.jsonl`,
and memory in `memory/`. The edition JSON is assembled in `edition.py`: the
editor writes the copy, but sources, confidence grades, gate scores and the
glance numbers are computed from the verified briefs, never invented.

---

## Cost

| Resource | Cost |
|---|---|
| Inference | $0.00 — local Ollama, or OpenRouter's free tier (rate-limited) |
| Search / discovery | $0.00 — RSS, arXiv, HN Algolia (all keyless) |
| Storage | local disk |

---

## Status

Verified working:

- deterministic pipeline: harvest → filter → cluster → continuity labelling
- quarantine store, keyed evidence lookup, entity-fidelity checking
- citation renumbering, orphan-source dropping
- all five gates: clean report passes; four planted defects each caught
- graph compiles; retry cap and gate routing enforced in Python
- budget circuit breaker


## Roadmap

- [x] Self-regenerating weekly edition (composed from live feeds, not a sample)
- [x] Hosted backend (OpenRouter) so the pipeline runs unattended in CI
- [x] `cron` scheduling — GitHub Actions, Mondays 15:00 IST
- [ ] Frozen golden dataset + planted-defect regression suite (the gates are
      already written as pure functions, so this is mostly harness)
- [ ] Structured trajectory logging to JSONL (local LangSmith substitute)
- [ ] Curated glossary term selection for auto-composed editions
- [ ] Daily cadence (needs a rolling 30-day memory window, not per-run centroids)
