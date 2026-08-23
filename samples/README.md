# Sample edition — 23 August 2026

Real output, committed so the repo shows what it produces without needing a run.

| File | What it is |
|---|---|
| `edition-2026-08-23.html` | **Open this first.** The web edition — animated jargon explainers, charts, every source linked. Self-contained; fonts embedded; works offline. |
| `briefing-2026-08-23.pdf` | The print edition. 5 pages, A4. What gets attached to the email. |
| `week-2026-08-23.json` | The structured run data both editions are rendered from. |

The email edition is not included as a file because it is built per recipient at
send time. Preview one with:

```bash
python -m newsroom.run --email-preview samples/week-2026-08-23.json
```

**Note on this sample:** the deterministic half of the pipeline — harvesting,
filtering, clustering, citation renumbering and all five quality gates — is the
shipped code operating on real sources. The prose in this particular edition was
hand-written, because the machine it was assembled on had no Ollama runtime. A
full local run produces the same structure from the agent tiers.
