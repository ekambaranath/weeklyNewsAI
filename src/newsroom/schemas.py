"""Typed contracts between tiers of the hierarchy.

Every message that crosses a tier boundary is a Pydantic model, not free text.
This is deliberate: the original Throughline had researchers return a
``TOPIC:/VERDICT:/SUMMARY:`` block that another *model* had to parse, which
means a parse failure is a silent quality failure. Typed contracts let the
deterministic supervisor read fields directly, and let a validation error be an
error rather than a hallucinated field.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["NEW", "DEVELOPING", "REPEAT"]
Verdict = Literal["KEEP", "SKIP"]
CheckResult = Literal["PASS", "FLAG"]


# --------------------------------------------------------------- harvest tier


class Item(BaseModel):
    """One harvested article. Produced by code, never by a model."""

    title: str
    url: str
    source: str = ""
    published: str = ""
    snippet: str = ""
    domain: str = ""
    quality: Literal["reputable", "unverified"] = "unverified"


class Cluster(BaseModel):
    """A deterministically discovered group of items about the same story."""

    cluster_id: str
    label: str = ""
    items: list[Item] = Field(default_factory=list)
    # Assigned by cross-run similarity, then confirmed or overridden by the editor.
    suggested_status: Status = "NEW"
    prior_similarity: float = 0.0
    prior_topic: str = ""

    def exemplars(self, n: int = 3) -> list[Item]:
        """The n highest-quality items, used to brief the editor cheaply."""
        ranked = sorted(self.items, key=lambda i: (i.quality != "reputable", i.title))
        return ranked[:n]


# ------------------------------------------------------------ Tier 1: editor


class TopicDecision(BaseModel):
    cluster_id: str
    topic: str = Field(description="Short, specific topic name")
    status: Status
    keep: bool
    why: str = Field(description="One line: why this matters, or why it is dropped")


class EditorialPlan(BaseModel):
    """The Managing Editor's call on what the run will cover."""

    decisions: list[TopicDecision]
    throughline: str = Field(
        default="", description="One line: the thread connecting the kept topics"
    )


# ------------------------------------------------------- Tier 2: research lead


class Assignment(BaseModel):
    """A research brief handed down from the Research Lead to a worker."""

    cluster_id: str
    topic: str
    status: Status
    depth: Literal["deep", "brief"] = "deep"
    angle: str = Field(default="", description="What specifically to establish")
    prior_summary: str = Field(
        default="", description="Last run's summary, for DEVELOPING topics only"
    )
    unsupported_claims: list[str] = Field(
        default_factory=list, description="Set on a re-dispatch; close these gaps"
    )


class ResearchAllocation(BaseModel):
    assignments: list[Assignment]


# ---------------------------------------------------------- Tier 3: researcher


class Claim(BaseModel):
    text: str = Field(description="One factual sentence")
    source_url: str = Field(description="The URL that substantiates this exact claim")


class Brief(BaseModel):
    """A worker's finished research on one topic."""

    cluster_id: str = ""
    topic: str = ""
    verdict: Verdict = "KEEP"
    reason: str = ""
    claims: list[Claim] = Field(default_factory=list)
    round: int = 0


# ------------------------------------------------ Tier 3: verifier / Tier 2 lead


class ClaimCheck(BaseModel):
    claim_text: str
    result: CheckResult
    note: str = ""


class VerificationReport(BaseModel):
    cluster_id: str = ""
    topic: str = ""
    result: CheckResult = "PASS"
    checks: list[ClaimCheck] = Field(default_factory=list)
    round: int = 0

    @property
    def unsupported(self) -> list[str]:
        return [c.claim_text for c in self.checks if c.result == "FLAG"]


# --------------------------------------------------------- Tier 2: publishing


class ReviewVerdict(BaseModel):
    approve: bool
    issues: list[str] = Field(default_factory=list)
    note: str = ""


class MemoryEntry(BaseModel):
    topic: str
    status: Status
    synopsis: str
    sources: list[str] = Field(default_factory=list)


# ------------------------------------------------ Tier 1: edition composition

# The editor writes only the judgement half of a story card. Everything factual
# — sources, their trust class, confidence, the gate scores, the four glance
# numbers — is computed from the verified briefs in edition.py, never invented
# here. That keeps the evidence chain of custody out of the model.

Section = Literal["shipped", "security", "governance", "research", "business"]


class StoryCopy(BaseModel):
    """The editorial copy for one story card, grounded in its verified claims."""

    cluster_id: str
    section: Section = Field(description="Which desk this story belongs to")
    headline: str = Field(description="Specific, factual, no hype. <= 12 words.")
    dek: str = Field(description="One sentence expanding the headline.")
    what_it_is: str = Field(description="What actually happened, plainly.")
    what_it_solves: str = Field(description="Why it matters / the problem it addresses.")
    what_it_changes: str = Field(description="What is different now for a builder.")
    should_you_act: str = Field(description="The one concrete 'so what' line.")
    confidence_note: str = Field(
        default="", description="One line on how solid the sourcing is."
    )


class EditionCopy(BaseModel):
    """The Managing Editor's finished copy for the whole edition."""

    thread: str = Field(description="One paragraph: the thread connecting the stories.")
    stories: list[StoryCopy] = Field(default_factory=list)
