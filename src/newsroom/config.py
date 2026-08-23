"""Load config.toml once at import and expose it as typed constants."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config.toml"
OUTPUT_DIR = ROOT / "output"
MEMORY_DIR = ROOT / "memory"
QUARANTINE_DIR = OUTPUT_DIR / "research"
REPORTS_DIR = OUTPUT_DIR / "reports"

if not CONFIG_PATH.is_file():
    raise RuntimeError(f"config.toml not found at {CONFIG_PATH}")

with open(CONFIG_PATH, "rb") as fh:
    _cfg = tomllib.load(fh)

MODELS = _cfg["models"]
BUDGET = _cfg["budget"]
HARVEST = _cfg["harvest"]
CLUSTER = _cfg["cluster"]
GATES = _cfg["gates"]

DENY_DOMAINS = frozenset(_cfg["trust"]["deny"])
ALLOW_DOMAINS = frozenset(_cfg["trust"]["allow"])

HYPE_TERMS = [t.lower() for t in GATES["hype_terms"]]
SENSITIVE_TERMS = [t.lower() for t in GATES["sensitive_terms"]]
