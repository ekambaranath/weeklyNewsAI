"""Terminology, with animated explainers.

An AI weekly has a readership problem: the security desk's vocabulary is not the
policy desk's, and neither is the builder's. Rather than either dumbing the copy
down or letting jargon gate the story, terms are marked up inline and explained
in the margin — the newspaper convention of a keyed sidebar, but with a moving
diagram instead of a paragraph.

Animation earns its place only where the concept IS a process. "Lethal trifecta"
is three conditions converging; showing them converge teaches it faster than a
sentence. "CVSS" is a number on a scale and gets no animation, because there is
no process to show.

Every explainer is inline SVG with CSS keyframes: no JavaScript, no external
requests, and it degrades to a static first frame in any renderer that ignores
CSS animation — which is exactly what the PDF and email editions need.
"""

from __future__ import annotations

# Shared animation styles. Scoped by a per-figure class so several explainers can
# sit on one page without their keyframes colliding.
EXPLAINER_CSS = """
@media (prefers-reduced-motion: reduce){
  .xp *{animation:none !important;}
}
.xp{width:100%;height:auto;display:block;}
.xp text{font-family:'PlexMono',ui-monospace,monospace;}

/* trifecta: three conditions sliding into overlap */
@keyframes tri-a{0%,8%{transform:translate(-26px,-14px)}38%,100%{transform:translate(0,0)}}
@keyframes tri-b{0%,8%{transform:translate(26px,-14px)}38%,100%{transform:translate(0,0)}}
@keyframes tri-c{0%,8%{transform:translate(0,26px)}38%,100%{transform:translate(0,0)}}
@keyframes danger{0%,42%{opacity:0;transform:scale(.6)}58%{opacity:1;transform:scale(1.06)}
  70%,100%{opacity:1;transform:scale(1)}}
@keyframes dangerpulse{0%,100%{opacity:.85}50%{opacity:.35}}
.tri-a{animation:tri-a 5s ease-in-out infinite;}
.tri-b{animation:tri-b 5s ease-in-out infinite;}
.tri-c{animation:tri-c 5s ease-in-out infinite;}
.tri-x{animation:danger 5s ease-in-out infinite;transform-origin:center;}
.tri-x circle{animation:dangerpulse 1.6s ease-in-out infinite;}

/* injection: a payload riding inside ordinary content */
@keyframes pkt{0%{offset-distance:0%}100%{offset-distance:100%}}
@keyframes reveal{0%,45%{opacity:0}55%,100%{opacity:1}}
@keyframes exec{0%,60%{opacity:.15}72%,100%{opacity:1}}
.inj-pkt{animation:pkt 4.5s linear infinite;}
.inj-reveal{animation:reveal 4.5s linear infinite;}
.inj-exec{animation:exec 4.5s linear infinite;}

/* token economics: output billed at a multiple of input */
@keyframes grow-in{0%{width:0}25%,100%{width:var(--w)}}
.tok-bar{animation:grow-in 3.6s ease-out infinite;}

/* threshold: a needle climbing into the red band */
@keyframes needle{0%{transform:rotate(-64deg)}55%,100%{transform:rotate(38deg)}}
@keyframes band{0%,50%{opacity:.25}62%,100%{opacity:1}}
.th-needle{animation:needle 4.2s cubic-bezier(.3,0,.2,1) infinite;transform-origin:100px 74px;}
.th-band{animation:band 4.2s ease-in-out infinite;}
"""


def _trifecta() -> str:
    """Labels sit outside the circles; inside they collide on overlap."""
    return """
<svg class="xp" viewBox="0 0 260 158" role="img" aria-label="Three conditions converging into a danger zone">
  <text x="60" y="16" text-anchor="middle" font-size="7.6" fill="#1D5FAE" font-weight="600">PRIVATE DATA</text>
  <text x="200" y="16" text-anchor="middle" font-size="7.6" fill="#8A6100" font-weight="600">UNTRUSTED INPUT</text>
  <text x="130" y="152" text-anchor="middle" font-size="7.6" fill="#0F6B4F" font-weight="600">A WAY TO SEND DATA OUT</text>

  <g class="tri-a">
    <circle cx="108" cy="68" r="33" fill="#1D5FAE" fill-opacity=".16" stroke="#1D5FAE" stroke-width="1.4"/>
    <line x1="66" y1="22" x2="88" y2="45" stroke="#1D5FAE" stroke-width=".8"/>
  </g>
  <g class="tri-b">
    <circle cx="152" cy="68" r="33" fill="#8A6100" fill-opacity=".16" stroke="#8A6100" stroke-width="1.4"/>
    <line x1="194" y1="22" x2="172" y2="45" stroke="#8A6100" stroke-width=".8"/>
  </g>
  <g class="tri-c">
    <circle cx="130" cy="104" r="33" fill="#0F6B4F" fill-opacity=".16" stroke="#0F6B4F" stroke-width="1.4"/>
    <line x1="130" y1="143" x2="130" y2="132" stroke="#0F6B4F" stroke-width=".8"/>
  </g>

  <g class="tri-x">
    <circle cx="130" cy="80" r="14" fill="#B3261E"/>
    <text x="130" y="83.5" text-anchor="middle" font-size="7.2" fill="#fff" font-weight="600">LEAK</text>
  </g>
</svg>"""


def _injection() -> str:
    return """
<svg class="xp" viewBox="0 0 260 110" role="img" aria-label="Hidden instruction travelling inside fetched content">
  <rect x="6" y="30" width="62" height="46" fill="#fff" stroke="#C9D2DE"/>
  <text x="37" y="24" text-anchor="middle" font-size="7" fill="#6B7A90">WEB PAGE</text>
  <line x1="14" y1="42" x2="60" y2="42" stroke="#C9D2DE" stroke-width="2.5"/>
  <line x1="14" y1="50" x2="60" y2="50" stroke="#C9D2DE" stroke-width="2.5"/>
  <line x1="14" y1="58" x2="52" y2="58" stroke="#B3261E" stroke-width="2.5"/>
  <text class="inj-reveal" x="37" y="86" text-anchor="middle" font-size="6.2" fill="#B3261E">hidden line</text>

  <path id="wire" d="M68,53 L152,53" stroke="#C9D2DE" stroke-width="1.2" stroke-dasharray="3 3" fill="none"/>
  <rect class="inj-pkt" x="-4" y="-4" width="8" height="8" fill="#B3261E"
        style="offset-path:path('M68,53 L152,53');"/>

  <rect x="152" y="26" width="60" height="54" fill="#101B2D"/>
  <text x="182" y="20" text-anchor="middle" font-size="7" fill="#6B7A90">THE MODEL</text>
  <text x="182" y="48" text-anchor="middle" font-size="6.6" fill="#8FA6C4">reads it all</text>
  <text x="182" y="60" text-anchor="middle" font-size="6.6" fill="#8FA6C4">as one stream</text>

  <g class="inj-exec">
    <path d="M212,53 L238,53" stroke="#B3261E" stroke-width="1.4"/>
    <path d="M234,49 L239,53 L234,57 Z" fill="#B3261E"/>
    <text x="226" y="44" text-anchor="middle" font-size="6.2" fill="#B3261E">OBEYS</text>
  </g>
</svg>"""


def _tokens() -> str:
    return """
<svg class="xp" viewBox="0 0 260 96" role="img" aria-label="Output tokens billed at several times the input rate">
  <text x="4" y="20" font-size="7" fill="#6B7A90">WHAT YOU SEND — INPUT</text>
  <rect x="4" y="26" width="46" height="13" fill="#1D5FAE" class="tok-bar" style="--w:46px"/>
  <text x="56" y="36" font-size="7.6" fill="#101B2D" font-weight="600">1×</text>

  <text x="4" y="60" font-size="7" fill="#6B7A90">WHAT IT WRITES BACK — OUTPUT</text>
  <rect x="4" y="66" width="230" height="13" fill="#B3261E" class="tok-bar" style="--w:230px"/>
  <text x="240" y="76" font-size="7.6" fill="#101B2D" font-weight="600">5×</text>

  <text x="4" y="92" font-size="6.2" fill="#6B7A90">An agent writes constantly — plans, tool calls, revisions. That is the bill.</text>
</svg>"""


def _threshold() -> str:
    return """
<svg class="xp" viewBox="0 0 200 92" role="img" aria-label="A capability gauge climbing into a red band">
  <path d="M28,74 A72,72 0 0 1 172,74" fill="none" stroke="#E3E8EF" stroke-width="11"/>
  <path class="th-band" d="M137,33 A72,72 0 0 1 172,74" fill="none" stroke="#B3261E" stroke-width="11"/>
  <g class="th-needle"><line x1="100" y1="74" x2="100" y2="22" stroke="#101B2D" stroke-width="2.4"/></g>
  <circle cx="100" cy="74" r="4.4" fill="#101B2D"/>
  <text x="28" y="88" font-size="6.4" fill="#6B7A90">LOW</text>
  <text x="150" y="88" font-size="6.4" fill="#B3261E">THRESHOLD</text>
</svg>"""


# key -> (term, one-line gloss, the fuller explanation, optional explainer svg)
TERMS: dict[str, dict] = {
    "lethal-trifecta": {
        "term": "Lethal trifecta",
        "short": "Three conditions that turn a helpful agent into a data leak.",
        "long": (
            "An agent is exposed when three things are true at once: it can reach "
            "private data, it reads content an attacker can write, and it has some "
            "way to send data out. Any one alone is fine. Together they are an "
            "exfiltration route, and no amount of careful prompting closes it — you "
            "have to remove one of the three."
        ),
        "svg": _trifecta,
        "seen_in": "Security",
    },
    "prompt-injection": {
        "term": "Prompt injection",
        "short": "Hiding an order inside content the model was only meant to read.",
        "long": (
            "A model receives instructions and material as one undifferentiated "
            "stream of text. So if a webpage it summarises contains a line phrased "
            "as a command, the model may simply follow it. There is no reliable "
            "separator between 'this is your task' and 'this is the thing you are "
            "reading' — which is why this keeps happening."
        ),
        "svg": _injection,
        "seen_in": "Security",
    },
    "output-tokens": {
        "term": "Input vs output tokens",
        "short": "The text a model writes costs several times the text you send it.",
        "long": (
            "Providers bill separately for text read and text generated, and "
            "generation typically runs about five times the rate. This matters "
            "disproportionately for agents, which spend their time writing — plans, "
            "tool calls, retries, revisions. Cut an output rate and you move agent "
            "economics; cut an input rate and you mostly move chat economics."
        ),
        "svg": _tokens,
        "seen_in": "Shipped",
    },
    "capability-threshold": {
        "term": "Capability threshold",
        "short": "A pre-agreed line where a lab commits to slowing down.",
        "long": (
            "Frontier labs publish frameworks naming capability levels that trigger "
            "extra safeguards or a pause. The idea only means anything if crossing "
            "one actually stops something — which is why a lab naming a specific "
            "model and a specific halt is a different kind of event from a lab "
            "publishing a policy."
        ),
        "svg": _threshold,
        "seen_in": "Lab governance",
    },
    "cvss": {
        "term": "CVSS score",
        "short": "A 0–10 severity rating for a security flaw.",
        "long": (
            "An industry scale weighing how easily a vulnerability is exploited and "
            "how much damage follows. Roughly: 7.0–8.9 is high, 9.0 and above is "
            "critical. It rates the flaw's shape, not whether anyone has used it."
        ),
        "svg": None,
        "seen_in": "Security",
    },
    "rl": {
        "term": "Reinforcement learning (RL)",
        "short": "The training stage that tunes a model's behaviour by reward.",
        "long": (
            "After a model learns language from raw text, RL shapes how it behaves — "
            "rewarding outputs judged better and discouraging the rest. It is the "
            "expensive, late stage of a training run, which is why pausing it is a "
            "meaningful and costly decision rather than a gesture."
        ),
        "svg": None,
        "seen_in": "Lab governance",
    },
}


def render_term(key: str, *, animated: bool = True) -> str:
    """One glossary entry as a self-contained block."""
    t = TERMS[key]
    figure = ""
    if animated and t["svg"]:
        figure = f'<div class="term-fig">{t["svg"]()}</div>'
    return f"""
    <div class="term" id="term-{key}">
      <div class="term-eyebrow">IN PLAIN TERMS &middot; {t["seen_in"]}</div>
      <div class="term-name">{t["term"]}</div>
      <div class="term-short">{t["short"]}</div>
      {figure}
      <div class="term-long">{t["long"]}</div>
    </div>"""


def render_glossary(keys: list[str], *, animated: bool = True) -> str:
    return "".join(render_term(k, animated=animated) for k in keys if k in TERMS)
