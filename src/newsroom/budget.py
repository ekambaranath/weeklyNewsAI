"""Run budget.

Local inference is free in dollars, which makes it tempting to treat it as
unbounded. It is not: it spends wall-clock and RAM, and an agent loop that
misbehaves will happily consume both until you kill it. This module gives the
deterministic supervisor a resource it can actually run out of, so the run
*degrades* (drops the lowest-ranked topic) instead of hanging.

Every LLM call in the system goes through ``spend``. When the budget is gone,
``spend`` returns False and callers return None — which the graph reads as
"drop this unit of work", not "crash".
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from newsroom.config import BUDGET


@dataclass
class Budget:
    max_seconds: float = float(BUDGET["max_wall_clock_seconds"])
    max_calls: int = int(BUDGET["max_llm_calls"])

    started: float = field(default_factory=time.monotonic)
    calls: int = 0
    by_label: dict[str, int] = field(default_factory=dict)
    exhausted_reason: str = ""

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    @property
    def remaining_calls(self) -> int:
        return max(0, self.max_calls - self.calls)

    def spend(self, label: str = "call") -> bool:
        """Record one LLM call. False means the budget is gone — stop cleanly."""
        if self.exhausted_reason:
            return False
        if self.calls >= self.max_calls:
            self.exhausted_reason = f"call ceiling reached ({self.max_calls})"
            return False
        if self.elapsed > self.max_seconds:
            self.exhausted_reason = f"wall-clock ceiling reached ({self.max_seconds:.0f}s)"
            return False
        self.calls += 1
        self.by_label[label] = self.by_label.get(label, 0) + 1
        return True

    def report(self) -> str:
        lines = [
            f"LLM calls: {self.calls}/{self.max_calls}",
            f"Wall clock: {self.elapsed:.0f}s/{self.max_seconds:.0f}s",
            "API cost:   $0.00 (all inference local)",
        ]
        if self.by_label:
            busiest = sorted(self.by_label.items(), key=lambda kv: -kv[1])[:5]
            lines.append("Busiest:    " + ", ".join(f"{k}×{v}" for k, v in busiest))
        if self.exhausted_reason:
            lines.append(f"DEGRADED:   {self.exhausted_reason}")
        return "\n".join("  " + line for line in lines)
