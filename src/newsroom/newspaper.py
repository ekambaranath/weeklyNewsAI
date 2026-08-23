"""The weekly newspaper — web edition.

Three editions come off one source, because each medium can carry a different
amount:

  * **web** (this module)  — animated explainers, full column layout, the
    reading experience
  * **email** (email_edition.py) — table-based, no JS, no web fonts; carries the
    lede and links out
  * **print** (render.py)  — A4 PDF, static first frames, the archive copy

Editorial structure follows a real weekly, not a blog: a masthead with a
dateline and edition number, ONE lead story given full width and a standfirst,
the remaining stories in a graded column grid, and marginal "In plain terms"
boxes keyed to the jargon in the adjacent copy.

The visual language is deliberately not broadsheet pastiche. It keeps the signal
briefing's instrument vocabulary — mono data type, category colour coding, the
source meter on every story — and borrows only newspaper *architecture*:
hierarchy, columns, folio. The subject is telemetry about a fast-moving field;
it should look like an instrument, not like The Times of 1962.

Fonts are base64-embedded so a single .html file opens anywhere with no network.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from newsroom.config import OUTPUT_DIR, ROOT
from newsroom.glossary import EXPLAINER_CSS, render_glossary
from newsroom.render import CONFIDENCE, SOURCE_CLASSES, _chart, _timeline

FONT_DIR = ROOT / "assets" / "fonts"

# Only the weights the layout actually uses — every extra face is ~80KB of
# base64 in a file people may open on a phone.
_EMBED = [
    ("Plex", "IBMPlexSans-Regular.woff2", 400),
    ("Plex", "IBMPlexSans-Medium.woff2", 500),
    ("Plex", "IBMPlexSans-SemiBold.woff2", 600),
    ("PlexCond", "IBMPlexSansCondensed-Bold.woff2", 700),
    ("PlexMono", "IBMPlexMono-Regular.woff2", 400),
    ("PlexMono", "IBMPlexMono-SemiBold.woff2", 600),
]


def _embedded_fonts() -> str:
    out = []
    for family, name, weight in _EMBED:
        path = FONT_DIR / name
        if not path.is_file():
            continue
        b64 = base64.b64encode(path.read_bytes()).decode()
        out.append(
            f"@font-face{{font-family:'{family}';font-weight:{weight};font-style:normal;"
            f"font-display:swap;src:url(data:font/woff2;base64,{b64}) format('woff2');}}"
        )
    return "".join(out)


CSS = """
*{margin:0;padding:0;box-sizing:border-box;}
:root{
  --paper:#F2F4F7; --card:#fff; --ink:#101B2D; --ink-2:#3C4A60; --ink-3:#6B7A90;
  --rule:#C9D2DE; --rule-soft:#E3E8EF; --measure:1180px;
}
html{scroll-behavior:smooth;}
body{font-family:'Plex',-apple-system,system-ui,sans-serif;background:var(--paper);
  color:var(--ink);font-size:16px;line-height:1.55;-webkit-font-smoothing:antialiased;}
.sheet{max-width:var(--measure);margin:0 auto;padding:0 24px 72px;}
a{color:inherit;}

/* ------------------------------------------------------------- masthead */
.mast{background:var(--ink);color:#fff;margin:0 -24px 0;padding:34px 32px 26px;}
.mast-inner{max-width:var(--measure);margin:0 auto;}
.mast-rule{display:flex;justify-content:space-between;align-items:flex-end;gap:24px;
  border-bottom:1px solid rgba(255,255,255,.2);padding-bottom:16px;flex-wrap:wrap;}
.title{font-family:'PlexCond',sans-serif;font-weight:700;font-size:clamp(38px,7vw,74px);
  line-height:.88;letter-spacing:-.025em;text-transform:uppercase;}
.title span{display:block;font-family:'PlexMono',monospace;font-size:11px;font-weight:400;
  letter-spacing:.42em;color:#8FA6C4;margin-top:12px;text-transform:uppercase;}
.dateline{font-family:'PlexMono',monospace;font-size:11px;color:#8FA6C4;
  text-align:right;line-height:2;white-space:nowrap;}
.dateline b{color:#fff;font-weight:600;}
.standfirst{max-width:70ch;margin-top:22px;font-size:clamp(16px,1.9vw,20px);line-height:1.5;
  color:#E7EEF6;font-weight:400;}
.standfirst-lbl{font-family:'PlexMono',monospace;font-size:10px;letter-spacing:.24em;
  color:#7E9ABE;margin-bottom:10px;}

/* --------------------------------------------------------------- glance */
.glance{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
  background:var(--ink);color:#fff;margin:0 -24px;padding:0 32px 30px;}
.glance-in{max-width:var(--measure);margin:0 auto;display:grid;
  grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:0;width:100%;}
.gc{padding:22px 20px 6px;border-top:2px solid rgba(255,255,255,.25);margin-right:1px;}
.gv{font-family:'PlexCond',sans-serif;font-weight:700;font-size:44px;line-height:1;
  letter-spacing:-.02em;}
.gv i{font-style:normal;font-size:19px;color:#8FA6C4;margin-left:2px;}
.gl{font-size:13px;font-weight:600;margin-top:8px;line-height:1.3;}
.gn{font-family:'PlexMono',monospace;font-size:10px;color:#7E9ABE;margin-top:6px;line-height:1.5;}

/* ------------------------------------------------------------- sections */
.sec{margin-top:44px;}
.sec-head{display:flex;align-items:center;gap:12px;border-bottom:2px solid;
  padding-bottom:8px;margin-bottom:20px;flex-wrap:wrap;}
.sec-dot{width:11px;height:11px;border-radius:50%;flex:0 0 auto;}
.sec-name{font-family:'PlexCond',sans-serif;font-weight:700;font-size:24px;
  text-transform:uppercase;letter-spacing:.03em;}
.sec-sub{font-size:14px;color:var(--ink-3);}
.sec-n{margin-left:auto;font-family:'PlexMono',monospace;font-size:10px;
  color:var(--ink-3);letter-spacing:.14em;}

/* ---------------------------------------------------------------- story */
.secgrid{display:grid;grid-template-columns:minmax(0,1fr) 296px;gap:24px;align-items:start;}
@media(max-width:900px){.secgrid{grid-template-columns:minmax(0,1fr);}}
.secrail{display:flex;flex-direction:column;gap:16px;}
.story{background:var(--card);border:1px solid var(--rule);border-left:4px solid;
  padding:26px 28px;}
.story.lead{padding:32px 34px;}
.kicker{font-family:'PlexMono',monospace;font-size:10px;letter-spacing:.16em;
  text-transform:uppercase;margin-bottom:10px;}
.hl{font-family:'PlexCond',sans-serif;font-weight:700;line-height:1.08;
  letter-spacing:-.015em;font-size:clamp(25px,3.4vw,38px);margin-bottom:12px;}
.story:not(.lead) .hl{font-size:clamp(21px,2.5vw,27px);}
.dek{font-size:17px;color:var(--ink-2);line-height:1.5;padding-bottom:18px;
  border-bottom:1px solid var(--rule-soft);margin-bottom:18px;}
.story:not(.lead) .dek{font-size:15.5px;}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(232px,1fr));gap:16px 30px;}
.f{border-top:1px solid var(--rule-soft);padding-top:11px;}
.fk{font-family:'PlexMono',monospace;font-size:10px;letter-spacing:.1em;
  text-transform:uppercase;color:var(--ink-3);margin-bottom:6px;}
.fv{font-size:15px;line-height:1.5;}

/* jargon marks in running copy */
.jar{border-bottom:1.5px dotted currentColor;cursor:help;font-weight:500;
  text-decoration:none;}
.jar:hover{background:#FFF3D6;}

/* --------------------------------------------------------------- charts */
.viz{margin:20px 0 0;padding:18px 20px;background:#F7F9FC;border:1px solid var(--rule-soft);}
.viz-title{font-family:'PlexMono',monospace;font-size:10px;letter-spacing:.16em;
  text-transform:uppercase;color:var(--ink-3);margin-bottom:14px;}
.viz-foot{font-family:'PlexMono',monospace;font-size:10px;color:var(--ink-3);
  margin-top:12px;line-height:1.5;}
.drow{display:grid;grid-template-columns:110px 1fr 108px;gap:14px;align-items:center;
  margin-bottom:12px;}
.dlab{font-size:14px;font-weight:500;}
.dbars{position:relative;height:26px;}
.dbar{position:absolute;height:11px;border-radius:1px;}
.dbar.b4{top:0;background:var(--rule);}
.dbar.af{top:14px;transition:width .9s cubic-bezier(.2,.7,.2,1);}
.dvals{font-family:'PlexMono',monospace;font-size:12.5px;text-align:right;line-height:1.35;}
.dvals s{color:var(--ink-3);display:block;font-size:11px;}
.dvals b{font-weight:600;}
.ddelta{font-family:'PlexMono',monospace;font-size:11px;font-weight:600;}
.chain{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;}
.link{border-top:3px solid;padding-top:11px;}
.link-n{font-family:'PlexMono',monospace;font-size:10px;letter-spacing:.16em;color:var(--ink-3);}
.link-t{font-family:'PlexCond',sans-serif;font-weight:700;font-size:18px;margin:4px 0 7px;
  text-transform:uppercase;letter-spacing:.02em;}
.link-d{font-size:13.5px;line-height:1.45;color:var(--ink-2);}
.tl{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:0;
  margin-top:18px;border-top:1px solid var(--rule);padding-top:14px;}
.tl-i{border-left:3px solid var(--rule);padding:0 14px 0 11px;}
.tl-i:last-child{border-left-color:#B3261E;}
.tl-d{font-family:'PlexMono',monospace;font-size:11px;font-weight:600;}
.tl-t{font-size:13.5px;color:var(--ink-2);line-height:1.42;margin-top:3px;}
.gauge{display:flex;align-items:center;}
.gtrack{flex:1;height:38px;background:var(--rule-soft);display:flex;overflow:hidden;}
.gfill{height:100%;display:flex;align-items:center;padding-left:12px;color:#fff;
  font-family:'PlexMono',monospace;font-size:13px;font-weight:600;
  transition:width 1.1s cubic-bezier(.2,.7,.2,1);}
.grest{flex:1;display:flex;align-items:center;padding-left:12px;color:var(--ink-3);
  font-family:'PlexMono',monospace;font-size:12px;}
.trend{display:flex;gap:38px;flex-wrap:wrap;}
.tcol{flex:1;min-width:170px;}
.tbars{display:flex;align-items:flex-end;gap:16px;height:120px;
  border-bottom:2px solid var(--ink);}
.tb{flex:1;position:relative;}
.tb-fill{width:100%;transition:height 1s cubic-bezier(.2,.7,.2,1);}
.tb-v{position:absolute;top:-22px;width:100%;text-align:center;
  font-family:'PlexMono',monospace;font-size:14px;font-weight:600;}
.tb-y{font-family:'PlexMono',monospace;font-size:11px;color:var(--ink-3);
  text-align:center;margin-top:7px;}
.tleg{font-size:13.5px;font-weight:600;margin-bottom:10px;display:flex;align-items:center;gap:8px;}
.tleg i{width:11px;height:11px;display:inline-block;}

/* ------------------------------------------------------------ provenance */
.prov{margin-top:20px;padding-top:14px;border-top:1px dashed var(--rule);}
.prov-top{display:flex;align-items:center;gap:14px;margin-bottom:10px;flex-wrap:wrap;}
.conf{font-family:'PlexMono',monospace;font-size:10px;font-weight:600;letter-spacing:.12em;
  color:#fff;padding:5px 9px;}
.ticks{display:flex;gap:5px;flex:1;min-width:90px;}
.tick{height:8px;flex:1;max-width:52px;}
.prov-count{font-family:'PlexMono',monospace;font-size:10px;color:var(--ink-3);letter-spacing:.08em;}
.prov-note{font-size:13.5px;color:var(--ink-2);line-height:1.5;margin-bottom:9px;}
.srcs{font-family:'PlexMono',monospace;font-size:11px;color:var(--ink-3);line-height:1.9;}
.srcs a{font-weight:600;color:var(--ink-2);text-decoration:none;border-bottom:1px solid var(--rule);}
.srcs a:hover{border-bottom-color:var(--ink-2);}

/* ---------------------------------------------------------------- terms */

.term{background:#FFFDF7;border:1px solid #E8DCBF;border-top:3px solid #8A6100;padding:16px 17px;}
.term-eyebrow{font-family:'PlexMono',monospace;font-size:9px;letter-spacing:.14em;
  color:#8A6100;margin-bottom:7px;}
.term-name{font-family:'PlexCond',sans-serif;font-weight:700;font-size:20px;
  line-height:1.1;margin-bottom:6px;}
.term-short{font-size:14px;font-weight:500;line-height:1.42;margin-bottom:11px;}
.term-fig{background:#fff;border:1px solid #EFE6D2;padding:9px;margin-bottom:11px;}
.term-long{font-size:13px;line-height:1.55;color:var(--ink-2);}

/* --------------------------------------------------------------- panels */
.panel{background:var(--card);border:1px solid var(--rule);padding:26px 28px;margin-top:22px;}
.panel-h{font-family:'PlexCond',sans-serif;font-weight:700;font-size:22px;text-transform:uppercase;
  letter-spacing:.03em;border-bottom:2px solid var(--ink);padding-bottom:9px;margin-bottom:16px;}
.panel-l{font-size:14.5px;color:var(--ink-2);line-height:1.55;margin-bottom:18px;max-width:78ch;}
.drop{display:grid;grid-template-columns:1fr 150px;gap:20px;padding:13px 0;
  border-bottom:1px solid var(--rule-soft);}
.drop:last-child{border-bottom:none;}
.drop-t{font-size:15px;font-weight:600;margin-bottom:4px;}
.drop-r{font-size:13.5px;color:var(--ink-2);line-height:1.45;}
.drop-v{font-family:'PlexMono',monospace;font-size:10px;font-weight:600;color:#B3261E;
  text-align:right;line-height:1.6;}
table.gates{width:100%;border-collapse:collapse;}
table.gates td{padding:11px 8px;border-bottom:1px solid var(--rule-soft);font-size:14px;}
table.gates td.st span{font-family:'PlexMono',monospace;font-size:10px;font-weight:600;
  color:#fff;background:#0F6B4F;padding:4px 8px;}
table.gates td.nm{font-family:'PlexMono',monospace;font-size:13px;}
table.gates td.vl{font-family:'PlexMono',monospace;font-size:13px;font-weight:600;text-align:right;}
table.gates td.dt{color:var(--ink-2);}
.legend{display:flex;gap:22px;flex-wrap:wrap;margin-top:16px;padding-top:14px;
  border-top:1px solid var(--rule-soft);}
.legend div{font-family:'PlexMono',monospace;font-size:10px;color:var(--ink-3);
  display:flex;align-items:center;gap:7px;}
.legend i{width:14px;height:8px;display:inline-block;}
.folio{margin-top:44px;padding-top:18px;border-top:2px solid var(--ink);display:flex;
  justify-content:space-between;font-family:'PlexMono',monospace;font-size:10px;
  color:var(--ink-3);letter-spacing:.1em;flex-wrap:wrap;gap:12px;}

/* reveal on scroll — quiet, once, and skipped entirely for reduced motion */
.rise{opacity:0;transform:translateY(14px);transition:opacity .55s ease,transform .55s ease;}
.rise.in{opacity:1;transform:none;}
@media(print){.rise{opacity:1;transform:none;}}
@media(prefers-reduced-motion:reduce){
  .rise{opacity:1;transform:none;transition:none;}
  html{scroll-behavior:auto;}
}
"""

JS = """
// Two jobs only: reveal blocks once as they enter, and animate the charts from
// zero the first time they are seen. Everything renders correctly with JS off —
// the final state is the default and these classes only add the transition.
document.addEventListener('DOMContentLoaded', function () {
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var targets = document.querySelectorAll('.rise');
  if (reduce || !('IntersectionObserver' in window)) {
    targets.forEach(function (t) { t.classList.add('in'); });
    document.querySelectorAll('[data-w]').forEach(function (el) {
      el.style.width = el.dataset.w; });
    document.querySelectorAll('[data-h]').forEach(function (el) {
      el.style.height = el.dataset.h; });
    return;
  }
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (!e.isIntersecting) return;
      e.target.classList.add('in');
      e.target.querySelectorAll('[data-w]').forEach(function (el) {
        el.style.width = el.dataset.w; });
      e.target.querySelectorAll('[data-h]').forEach(function (el) {
        el.style.height = el.dataset.h; });
      io.unobserve(e.target);
    });
  }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });
  targets.forEach(function (t) { io.observe(t); });
});
"""


def _web_chart(chart: dict | None, hue: str) -> str:
    """Charts that animate in. Falls back to the static print renderer."""
    if not chart:
        return ""
    kind = chart["type"]

    if kind == "delta":
        rows = []
        for r in chart["rows"]:
            wa = (r["after"] / r["before"] * 100) if r["before"] else 0
            rows.append(f"""
            <div class="drow"><div class="dlab">{r["label"]}</div>
              <div class="dbars">
                <div class="dbar b4" style="width:100%"></div>
                <div class="dbar af" data-w="{wa:.1f}%" style="width:0;background:{hue}"></div>
              </div>
              <div class="dvals"><s>{r["fmt"] % r["before"]}</s><b>{r["fmt"] % r["after"]}</b>
                <span class="ddelta" style="color:{hue}">{r["delta"]}</span></div></div>""")
        body = "".join(rows) + ('<div class="viz-foot">Each bar is scaled to its own '
                                'previous rate — grey is the old price, colour the new.</div>')
        return f'<div class="viz"><div class="viz-title">{chart["title"]}</div>{body}</div>'

    if kind == "gauge":
        pct = chart["pct"]
        return f"""<div class="viz"><div class="viz-title">{chart["title"]}</div>
          <div class="gauge"><div class="gtrack">
            <div class="gfill" data-w="{pct}%" style="width:0;background:{hue}">{pct}%</div>
            <div class="grest">{chart["offlabel"]} — {100 - pct}%</div></div></div>
          <div class="viz-foot">{chart["onlabel"]} · {chart["foot"]}</div></div>"""

    if kind == "trend":
        cols = []
        for s in chart["series"]:
            bars = "".join(
                f"""<div class="tb"><div class="tb-v" style="color:{s["hue"]}">{v}%</div>
                  <div class="tb-fill" data-h="{v / 60 * 120:.0f}px"
                       style="height:0;background:{s["hue"]}"></div>
                  <div class="tb-y">{y}</div></div>"""
                for y, v in s["points"]
            )
            cols.append(f"""<div class="tcol">
              <div class="tleg"><i style="background:{s["hue"]}"></i>{s["label"]}</div>
              <div class="tbars">{bars}</div></div>""")
        return (f'<div class="viz"><div class="viz-title">{chart["title"]}</div>'
                f'<div class="trend">{"".join(cols)}</div>'
                f'<div class="viz-foot">{chart["foot"]}</div></div>')

    return _chart(chart, hue)  # chain diagram: identical in both editions


def _mark_jargon(text: str, terms: list[str], used: set[str]) -> str:
    """Link the FIRST occurrence in the whole edition of each keyed phrase.

    Once per document, not once per field: a term underlined in every paragraph
    stops reading as a helpful aid and starts reading as a rash. ``used`` is
    threaded through the build so the mark lands on the earliest mention only.
    """
    from newsroom.glossary import TERMS

    for key in terms:
        if key in used:
            continue
        phrase = TERMS[key]["term"].split(" (")[0]
        for variant in (phrase, phrase.lower(), phrase.upper()):
            if variant in text:
                text = text.replace(
                    variant,
                    f'<a class="jar" href="#term-{key}" '
                    f'title="{TERMS[key]["short"]}">{variant}</a>',
                    1,
                )
                used.add(key)
                break
    return text


def _provenance(item: dict) -> str:
    srcs = item["sources"]
    strong = sum(1 for s in srcs if s["cls"] in ("primary", "independent"))
    order = {"primary": 0, "independent": 1, "trade": 2, "vendor": 3, "conflict": 4}
    ticks = "".join(
        f'<div class="tick" style="background:{SOURCE_CLASSES[s["cls"]][0]}"></div>'
        for s in sorted(srcs, key=lambda s: order.get(s["cls"], 9))
    )
    links = " &nbsp;·&nbsp; ".join(
        f'<a href="{s["url"]}" target="_blank" rel="noopener">{s["outlet"]}</a> '
        f'{SOURCE_CLASSES[s["cls"]][1]}'
        for s in srcs
    )
    conf = item["confidence"]
    return f"""<div class="prov"><div class="prov-top">
        <div class="conf" style="background:{CONFIDENCE[conf]}">{conf} CONFIDENCE</div>
        <div class="ticks">{ticks}</div>
        <div class="prov-count">{strong}/{len(srcs)} PRIMARY OR INDEPENDENT</div></div>
      <div class="prov-note">{item["confidence_note"]}</div>
      <div class="srcs">{links}</div></div>"""


def _story(item: dict, cat: dict, lead: bool, terms: list[str], used: set[str]) -> str:
    fields = "".join(
        f'<div class="f"><div class="fk">{k}</div>'
        f'<div class="fv">{_mark_jargon(v, terms, used)}</div></div>'
        for k, v in item["fields"].items()
    )
    return f"""<article class="story {"lead" if lead else ""} rise"
        style="border-left-color:{cat["hue"]}">
      <div class="kicker" style="color:{cat["hue"]}">{cat["name"]}</div>
      <h2 class="hl">{item["headline"]}</h2>
      <p class="dek">{item["dek"]}</p>
      <div class="cols">{fields}</div>
      {_web_chart(item.get("chart"), cat["hue"])}
      {_timeline(item.get("timeline", []))}
      {_provenance(item)}
    </article>"""


def build_web(data: dict) -> str:
    cats = data["categories"]
    term_keys = list(data.get("terms", []))
    marked: set[str] = set()
    from newsroom.glossary import TERMS

    stories = []
    first = True
    for cat in cats:
        # Which terms belong beside this section, in the order they were listed.
        mine = [k for k in term_keys if TERMS[k]["seen_in"] == cat["name"]]
        body = "".join(
            _story(item, cat, first and not i, term_keys, marked)
            for i, item in enumerate(cat["items"])
        )
        first = False
        rail = (
            f'<aside class="secrail">{render_glossary(mine)}</aside>' if mine else ""
        )
        stories.append(
            f"""<section class="sec"><div class="sec-head" style="border-color:{cat["hue"]}">
              <span class="sec-dot" style="background:{cat["hue"]}"></span>
              <span class="sec-name">{cat["name"]}</span>
              <span class="sec-sub">{cat["sub"]}</span>
              <span class="sec-n">{len(cat["items"])} SIGNAL</span></div>
              <div class="secgrid"><div>{body}</div>{rail}</div>
            </section>"""
        )

    glance = "".join(
        f'<div class="gc"><div class="gv">{g["value"]}<i>{g["unit"]}</i></div>'
        f'<div class="gl">{g["label"]}</div><div class="gn">{g["note"]}</div></div>'
        for g in data["glance"]
    )
    dropped = "".join(
        f'<div class="drop"><div><div class="drop-t">{d["topic"]}</div>'
        f'<div class="drop-r">{d["reason"]}</div></div>'
        f'<div class="drop-v">{d["verdict"]}</div></div>'
        for d in data["dropped"]
    )
    gates = "".join(
        f'<tr><td class="st"><span>{"PASS" if g["pass"] else "FAIL"}</span></td>'
        f'<td class="nm">{g["name"]}</td><td class="vl">{g["score"]}</td>'
        f'<td class="dt">{g["detail"]}</td></tr>'
        for g in data["gates"]
    )
    legend = "".join(
        f'<div><i style="background:{c}"></i>{label}</div>'
        for c, label in SOURCE_CLASSES.values()
    )
    total_sources = sum(len(i["sources"]) for c in cats for i in c["items"])
    signals = sum(len(c["items"]) for c in cats)

    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>This Week in AI — Week {data["week"]}, {data["range"]}</title>
<meta name="description" content="{data["thread"][:150]}">
<style>{_embedded_fonts()}{CSS}{EXPLAINER_CSS}</style></head>
<body><div class="sheet">

<header class="mast"><div class="mast-inner">
  <div class="mast-rule">
    <div class="title">This Week in AI<span>Weekly signal briefing</span></div>
    <div class="dateline">EDITION <b>{data["week"]}</b> &nbsp; {data["range"]}<br>
      <b>{signals}</b> signals &nbsp;·&nbsp; <b>{len(data["dropped"])}</b> dropped
      &nbsp;·&nbsp; <b>{total_sources}</b> sources<br>
      ISSUED <b>{data["issued"]}</b></div>
  </div>
  <div class="standfirst"><div class="standfirst-lbl">THE THREAD</div>{data["thread"]}</div>
</div></header>

<div class="glance"><div class="glance-in">{glance}</div></div>

<main>{"".join(stories)}

    <div class="panel rise"><div class="panel-h">What was dropped, and why</div>
      <p class="panel-l">Four candidate stories were researched and cut before
      publication. A paper that prints only what survived is hiding its own error
      rate, so the rejections run with their reasons.</p>{dropped}</div>

    <div class="panel rise"><div class="panel-h">Verification ledger</div>
      <p class="panel-l">Five deterministic checks run on the assembled edition
      before it may publish. They are plain functions, not model judgement, and
      they are why no claim above appears without an attached source.</p>
      <table class="gates">{gates}</table>
      <div class="legend">{legend}</div></div>

    <div class="panel rise"><div class="panel-h">How to read the source meter</div>
      <p class="panel-l">Every story carries a strip of ticks, one per source,
      coloured by class. <b>Primary</b> is the originating document. <b>Independent</b>
      is a newsroom doing its own reporting. <b>Vendor claim</b> is a company
      describing its own product or process — reported as a claim, never as a
      verified fact. <b>Conflicting</b> flags a source that disagrees with the
      others, printed rather than quietly resolved. A grade of MEDIUM does not mean
      the story is doubtful; it means the strongest available source is a vendor,
      or sources disagree on a detail, and you should check before acting.</p></div>

    <div class="folio">
      <span>THIS WEEK IN AI · EDITION {data["week"]}</span>
      <span>ASSEMBLED LOCALLY · NO API COST</span>
      <span>EVERY CLAIM CARRIES ITS SOURCE CLASS</span>
    </div>
  </main>

</div><script>{JS}</script></body></html>"""


def render_web(data_path: Path | str, out_path: Path | str | None = None) -> Path:
    data = json.loads(Path(data_path).read_text(encoding="utf-8"))
    out = Path(out_path) if out_path else OUTPUT_DIR / f"edition-{data['issued']}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_web(data), encoding="utf-8")
    return out
