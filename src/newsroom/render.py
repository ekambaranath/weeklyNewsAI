"""Render a run into a designed PDF briefing.

Markdown was the wrong deliverable. A weekly briefing is read once, fast, by
someone deciding whether anything this week requires action — that is a
triage document, and triage documents are visual.

Two design commitments drive everything here:

**Categorisation over chronology.** A story is filed by what KIND of thing it is
— shipped, security, lab governance, policy, sentiment — and every item answers
the same four questions in the same order: what it is, what problem it solves or
exposes, what it changes, whether you should act. Uniform fields make items
comparable at a glance; prose does not.

**Provenance on every card.** The signature element is the source meter: a strip
of ticks coloured by source class (primary, independent, trade, vendor,
conflicting) plus a confidence grade. The pipeline already computes gate scores;
hiding them in a log and printing confident prose would be the dishonest choice.
A claim sourced only to a vendor blog LOOKS different from one with four
independent outlets behind it, on the page, without the reader having to dig.

Rendering is Chromium via Playwright — real CSS, real page breaks, fonts
embedded from assets/fonts so output is byte-identical offline.
"""

from __future__ import annotations

import json
from pathlib import Path

from newsroom.config import OUTPUT_DIR, ROOT

FONT_DIR = ROOT / "assets" / "fonts"

# Source classes, ordered weakest to strongest. Drives both the meter colour and
# the ordering of the legend.
SOURCE_CLASSES = {
    "primary": ("#0F6B4F", "Primary"),
    "independent": ("#1D5FAE", "Independent"),
    "trade": ("#8A6100", "Trade press"),
    "vendor": ("#B3261E", "Vendor claim"),
    "conflict": ("#5B3FA8", "Conflicting"),
}

CONFIDENCE = {
    "HIGH": "#0F6B4F",
    "MEDIUM": "#8A6100",
    "LOW": "#B3261E",
}


def _font_face(family: str, file: str, weight: int, path: Path) -> str:
    return f"""@font-face{{font-family:'{family}';src:url('{(path / file).as_uri()}') format('woff2');font-weight:{weight};font-style:normal;font-display:block;}}"""


def _fonts() -> str:
    faces = [
        ("Plex", "IBMPlexSans-Light.woff2", 300),
        ("Plex", "IBMPlexSans-Regular.woff2", 400),
        ("Plex", "IBMPlexSans-Medium.woff2", 500),
        ("Plex", "IBMPlexSans-SemiBold.woff2", 600),
        ("Plex", "IBMPlexSans-Bold.woff2", 700),
        ("PlexCond", "IBMPlexSansCondensed-Regular.woff2", 400),
        ("PlexCond", "IBMPlexSansCondensed-SemiBold.woff2", 600),
        ("PlexCond", "IBMPlexSansCondensed-Bold.woff2", 700),
        ("PlexMono", "IBMPlexMono-Regular.woff2", 400),
        ("PlexMono", "IBMPlexMono-Medium.woff2", 500),
        ("PlexMono", "IBMPlexMono-SemiBold.woff2", 600),
    ]
    return "\n".join(_font_face(f, n, w, FONT_DIR) for f, n, w in faces)


CSS = """
*{margin:0;padding:0;box-sizing:border-box;}
:root{
  --paper:#F2F4F7; --card:#FFFFFF; --ink:#101B2D; --ink-2:#3C4A60;
  --ink-3:#6B7A90; --rule:#C9D2DE; --rule-soft:#E3E8EF;
}
@page{size:A4;margin:12mm 14mm 15mm;}
html{-webkit-print-color-adjust:exact;print-color-adjust:exact;background:var(--paper);}
body{font-family:'Plex',sans-serif;background:var(--paper);color:var(--ink);
  font-size:9.4pt;line-height:1.5;font-feature-settings:"kern","liga";}

/* ---------------------------------------------------------- masthead */
.masthead{background:var(--ink);color:#fff;margin:0 0 4mm;padding:6mm 7mm 5mm;}
.mast-top{display:flex;justify-content:space-between;align-items:baseline;
  border-bottom:1px solid rgba(255,255,255,.22);padding-bottom:3mm;margin-bottom:4mm;}
.wordmark{font-family:'PlexCond',sans-serif;font-weight:700;font-size:23pt;
  letter-spacing:-.02em;line-height:.95;text-transform:uppercase;}
.wordmark span{display:block;font-size:9.5pt;font-weight:400;letter-spacing:.3em;
  color:#8FA6C4;margin-top:2.5mm;}
.mast-meta{font-family:'PlexMono',monospace;font-size:7.6pt;text-align:right;
  color:#8FA6C4;line-height:1.9;}
.mast-meta b{color:#fff;font-weight:500;}
.thread-label{font-family:'PlexMono',monospace;font-size:6.6pt;letter-spacing:.22em;
  color:#7E9ABE;margin-bottom:2mm;}
.thread{font-family:'Plex',sans-serif;font-weight:300;font-size:9.8pt;line-height:1.44;
  color:#EAF0F7;max-width:158mm;}
.thread b{font-weight:600;color:#fff;}

/* ------------------------------------------------------------ glance */
.glance{display:grid;grid-template-columns:repeat(4,1fr);gap:0;margin-bottom:5mm;
  border-top:2px solid var(--ink);border-bottom:1px solid var(--rule);}
.gcell{padding:3mm 3.5mm 3.5mm;border-right:1px solid var(--rule-soft);}
.gcell:last-child{border-right:none;}
.gval{font-family:'PlexCond',sans-serif;font-weight:700;font-size:22pt;line-height:1;
  letter-spacing:-.02em;}
.gval i{font-style:normal;font-size:12pt;font-weight:600;color:var(--ink-3);margin-left:1px;}
.glabel{font-size:8.2pt;font-weight:600;line-height:1.3;margin-top:2mm;}
.gnote{font-family:'PlexMono',monospace;font-size:6.8pt;color:var(--ink-3);
  margin-top:1.5mm;line-height:1.4;}

/* ----------------------------------------------------------- section */
.cat{margin-bottom:4.5mm;}
.cat-head{break-after:avoid-page;}
.cat-head{display:flex;align-items:baseline;gap:3mm;padding-bottom:1.5mm;
  border-bottom:2px solid;margin-bottom:3mm;}
.cat-dot{width:9px;height:9px;border-radius:50%;flex:0 0 auto;align-self:center;}
.cat-name{font-family:'PlexCond',sans-serif;font-weight:700;font-size:12.5pt;
  text-transform:uppercase;letter-spacing:.04em;}
.cat-sub{font-size:8.4pt;color:var(--ink-3);font-weight:400;}
.cat-count{margin-left:auto;font-family:'PlexMono',monospace;font-size:7pt;
  color:var(--ink-3);letter-spacing:.1em;}

/* -------------------------------------------------------------- card */
.card{background:var(--card);border:1px solid var(--rule);border-left:3px solid;
  padding:3.5mm 4mm;margin-bottom:3mm;page-break-inside:avoid;}
.headline{font-family:'PlexCond',sans-serif;font-weight:700;font-size:12.6pt;
  line-height:1.12;letter-spacing:-.01em;margin-bottom:1.2mm;}
.dek{font-size:8.4pt;color:var(--ink-2);line-height:1.36;font-weight:400;
  padding-bottom:2mm;margin-bottom:2mm;border-bottom:1px solid var(--rule-soft);}
.fields{display:grid;grid-template-columns:1fr 1fr;gap:2.5mm 5mm;}
.field{border-top:1px solid var(--rule-soft);padding-top:1.8mm;}
.fkey{font-family:'PlexMono',monospace;font-size:6.5pt;letter-spacing:.08em;
  text-transform:uppercase;color:var(--ink-3);margin-bottom:1mm;}
.fval{font-size:7.9pt;line-height:1.34;color:var(--ink);}

/* ------------------------------------------------------------- charts */
.viz{margin:2.5mm 0 0;padding:2.5mm 3mm;background:#F7F9FC;border:1px solid var(--rule-soft);}
.viz-title{font-family:'PlexMono',monospace;font-size:6.9pt;letter-spacing:.12em;
  text-transform:uppercase;color:var(--ink-3);margin-bottom:3.5mm;}
.viz-foot{font-family:'PlexMono',monospace;font-size:6.4pt;color:var(--ink-3);
  margin-top:3mm;line-height:1.4;}
.drow{display:grid;grid-template-columns:24mm 1fr 20mm;gap:3mm;align-items:center;
  margin-bottom:2.6mm;}
.dlab{font-size:8.2pt;font-weight:500;}
.dbars{position:relative;height:15px;}
.dbar{position:absolute;height:6px;border-radius:1px;}
.dbar.b4{top:0;background:var(--rule);}
.dbar.af{top:8px;}
.dvals{font-family:'PlexMono',monospace;font-size:7.4pt;text-align:right;line-height:1.35;}
.dvals s{color:var(--ink-3);text-decoration:line-through;display:block;font-size:6.8pt;}
.dvals b{font-weight:600;}
.ddelta{font-family:'PlexMono',monospace;font-size:6.7pt;font-weight:600;}

.chain{display:grid;grid-template-columns:repeat(3,1fr);gap:2.5mm;}
.link{border-top:2px solid;padding-top:2.5mm;}
.link-n{font-family:'PlexMono',monospace;font-size:6.6pt;letter-spacing:.14em;
  color:var(--ink-3);}
.link-t{font-family:'PlexCond',sans-serif;font-weight:700;font-size:10.5pt;
  margin:.8mm 0 1.5mm;text-transform:uppercase;letter-spacing:.02em;}
.link-d{font-size:7.2pt;line-height:1.36;color:var(--ink-2);}

.tl{display:flex;gap:0;margin-top:3.5mm;border-top:1px solid var(--rule);padding-top:3mm;}
.tl-i{flex:1;padding-right:3mm;border-left:2px solid var(--rule);padding-left:2.5mm;}
.tl-i:last-child{border-left-color:#B3261E;}
.tl-d{font-family:'PlexMono',monospace;font-size:6.8pt;font-weight:600;}
.tl-t{font-size:7.6pt;color:var(--ink-2);line-height:1.38;margin-top:.6mm;}

.gauge{display:flex;align-items:center;gap:5mm;}
.gtrack{flex:1;height:22px;background:var(--rule-soft);display:flex;overflow:hidden;}
.gfill{height:100%;display:flex;align-items:center;padding-left:2.5mm;
  font-family:'PlexMono',monospace;font-size:7.6pt;font-weight:600;color:#fff;}
.grest{flex:1;display:flex;align-items:center;padding-left:2.5mm;
  font-family:'PlexMono',monospace;font-size:7.4pt;color:var(--ink-3);}

.trend{display:flex;gap:7mm;align-items:flex-end;}
.tcol{flex:1;}
.tbars{display:flex;align-items:flex-end;gap:3mm;height:22mm;
  border-bottom:1.5px solid var(--ink);padding-bottom:0;}
.tb{flex:1;position:relative;}
.tb-fill{width:100%;}
.tb-v{position:absolute;top:-5mm;width:100%;text-align:center;
  font-family:'PlexMono',monospace;font-size:8pt;font-weight:600;}
.tb-y{font-family:'PlexMono',monospace;font-size:6.8pt;color:var(--ink-3);
  text-align:center;margin-top:1.5mm;}
.tleg{font-size:7.8pt;font-weight:600;margin-bottom:2.5mm;display:flex;
  align-items:center;gap:2mm;}
.tleg i{width:8px;height:8px;display:inline-block;}

/* --------------------------------------------------- provenance meter */
.prov{margin-top:3mm;padding-top:2.5mm;border-top:1px dashed var(--rule);}
.prov-top{display:flex;align-items:center;gap:3mm;margin-bottom:2.5mm;}
.conf{font-family:'PlexMono',monospace;font-size:6.8pt;font-weight:600;
  letter-spacing:.1em;color:#fff;padding:1mm 2.2mm;}
.ticks{display:flex;gap:1.4mm;flex:1;}
.tick{height:5px;flex:1;max-width:13mm;}
.prov-count{font-family:'PlexMono',monospace;font-size:6.6pt;color:var(--ink-3);
  letter-spacing:.06em;}
.prov-note{font-size:7pt;color:var(--ink-2);line-height:1.34;margin-bottom:1.2mm;}
.srcs{font-family:'PlexMono',monospace;font-size:6.3pt;color:var(--ink-3);
  line-height:1.5;}
.srcs em{font-style:normal;font-weight:600;}
.srcs u{text-decoration:none;}

/* ------------------------------------------------------------ ledger */
.panel{background:var(--card);border:1px solid var(--rule);padding:5mm 5.5mm;
  margin-bottom:5mm;page-break-inside:avoid;}
.panel-h{font-family:'PlexCond',sans-serif;font-weight:700;font-size:13.5pt;
  text-transform:uppercase;letter-spacing:.04em;padding-bottom:2mm;
  border-bottom:2px solid var(--ink);margin-bottom:3.5mm;}
.panel-lede{font-size:8.7pt;color:var(--ink-2);line-height:1.45;margin-bottom:4mm;}
.drop{display:grid;grid-template-columns:1fr 30mm;gap:4mm;padding:2.8mm 0;
  border-bottom:1px solid var(--rule-soft);}
.drop:last-child{border-bottom:none;}
.drop-t{font-size:8.8pt;font-weight:600;margin-bottom:1mm;}
.drop-r{font-size:8pt;color:var(--ink-2);line-height:1.42;}
.drop-v{font-family:'PlexMono',monospace;font-size:6.6pt;font-weight:600;
  color:#B3261E;text-align:right;letter-spacing:.04em;line-height:1.45;}
table.gates{width:100%;border-collapse:collapse;}
table.gates td{padding:2.4mm 2mm;border-bottom:1px solid var(--rule-soft);
  font-size:8.3pt;vertical-align:middle;}
table.gates td.g-st{font-family:'PlexMono',monospace;font-size:6.8pt;font-weight:600;
  color:#fff;width:14mm;}
table.gates td.g-st span{background:#0F6B4F;padding:1mm 2mm;}
table.gates td.g-n{font-family:'PlexMono',monospace;font-size:8pt;width:40mm;}
table.gates td.g-v{font-family:'PlexMono',monospace;font-size:8pt;font-weight:600;
  width:16mm;text-align:right;}
table.gates td.g-d{color:var(--ink-2);font-size:8pt;}
.legend{display:flex;gap:5mm;flex-wrap:wrap;margin-top:3mm;padding-top:3mm;
  border-top:1px solid var(--rule-soft);}
.legend div{font-family:'PlexMono',monospace;font-size:6.6pt;color:var(--ink-3);
  display:flex;align-items:center;gap:1.6mm;}
.legend i{width:9px;height:5px;display:inline-block;}

"""


# ------------------------------------------------------------- components


def _ticks(sources: list[dict]) -> str:
    order = {"primary": 0, "independent": 1, "trade": 2, "vendor": 3, "conflict": 4}
    ranked = sorted(sources, key=lambda s: order.get(s["cls"], 9))
    return "".join(
        f'<div class="tick" style="background:{SOURCE_CLASSES.get(s["cls"], ("#999",""))[0]}"></div>'
        for s in ranked
    )


def _provenance(item: dict) -> str:
    sources = item["sources"]
    strong = sum(1 for s in sources if s["cls"] in ("primary", "independent"))
    conf = item["confidence"]
    srcs = " &nbsp;·&nbsp; ".join(
        f'<em>{s["outlet"]}</em> <u>{SOURCE_CLASSES.get(s["cls"], ("", "?"))[1]}</u>'
        for s in sources
    )
    return f"""
    <div class="prov">
      <div class="prov-top">
        <div class="conf" style="background:{CONFIDENCE[conf]}">{conf} CONFIDENCE</div>
        <div class="ticks">{_ticks(sources)}</div>
        <div class="prov-count">{strong}/{len(sources)} PRIMARY OR INDEPENDENT</div>
      </div>
      <div class="prov-note">{item["confidence_note"]}</div>
      <div class="srcs">{srcs}</div>
    </div>"""


def _chart(chart: dict, hue: str) -> str:
    if not chart:
        return ""
    kind = chart["type"]
    body = ""

    if kind == "delta":
        # Each row is scaled against its OWN before-value, not a global peak.
        # A global peak makes a $0.40 row invisible next to a $30 row, which
        # hides exactly the comparison the chart exists to show.
        rows = []
        for r in chart["rows"]:
            wa = (r["after"] / r["before"] * 100) if r["before"] else 0
            rows.append(f"""
            <div class="drow">
              <div class="dlab">{r["label"]}</div>
              <div class="dbars">
                <div class="dbar b4" style="width:100%"></div>
                <div class="dbar af" style="width:{wa:.1f}%;background:{hue}"></div>
              </div>
              <div class="dvals"><s>{r["fmt"] % r["before"]}</s>
                <b>{r["fmt"] % r["after"]}</b>
                <span class="ddelta" style="color:{hue}">{r["delta"]}</span></div>
            </div>""")
        body = "".join(rows) + (
            '<div class="viz-foot">Each bar scaled to its own previous rate; '
            'grey is the old price, colour is the new one.</div>'
        )

    elif kind == "chain":
        body = '<div class="chain">' + "".join(
            f"""<div class="link" style="border-color:{hue}">
              <div class="link-n">LINK {s["n"]}</div>
              <div class="link-t">{s["t"]}</div>
              <div class="link-d">{s["d"]}</div></div>"""
            for s in chart["steps"]
        ) + "</div>"

    elif kind == "gauge":
        pct = chart["pct"]
        body = f"""<div class="gauge"><div class="gtrack">
            <div class="gfill" style="width:{pct}%;background:{hue}">{pct}%</div>
            <div class="grest">{chart["offlabel"]} — {100 - pct}%</div>
          </div></div>
          <div class="viz-foot">{chart["onlabel"]} · {chart["foot"]}</div>"""
        return f'<div class="viz"><div class="viz-title">{chart["title"]}</div>{body}</div>'

    elif kind == "trend":
        cols = []
        for s in chart["series"]:
            bars = []
            for year, val in s["points"]:
                h = val / 60 * 22
                bars.append(f"""<div class="tb">
                    <div class="tb-v" style="color:{s["hue"]}">{val}%</div>
                    <div class="tb-fill" style="height:{h:.1f}mm;background:{s["hue"]}"></div>
                    <div class="tb-y">{year}</div></div>""")
            cols.append(f"""<div class="tcol">
                <div class="tleg"><i style="background:{s["hue"]}"></i>{s["label"]}</div>
                <div class="tbars">{"".join(bars)}</div></div>""")
        body = '<div class="trend">' + "".join(cols) + "</div>"

    foot = f'<div class="viz-foot">{chart["foot"]}</div>' if chart.get("foot") else ""
    return f'<div class="viz"><div class="viz-title">{chart["title"]}</div>{body}{foot}</div>'


def _timeline(steps: list[dict]) -> str:
    if not steps:
        return ""
    return '<div class="tl">' + "".join(
        f'<div class="tl-i"><div class="tl-d">{s["d"]}</div><div class="tl-t">{s["t"]}</div></div>'
        for s in steps
    ) + "</div>"


def _card(item: dict, hue: str) -> str:
    fields = '<div class="fields">' + "".join(
        f'<div class="field"><div class="fkey">{k}</div><div class="fval">{v}</div></div>'
        for k, v in item["fields"].items()
    ) + "</div>"
    return f"""
    <div class="card" style="border-left-color:{hue}">
      <div class="headline">{item["headline"]}</div>
      <div class="dek">{item["dek"]}</div>
      {fields}
      {_chart(item.get("chart"), hue)}
      {_timeline(item.get("timeline", []))}
      {_provenance(item)}
    </div>"""


def _category(cat: dict) -> str:
    n = len(cat["items"])
    cards = "".join(_card(i, cat["hue"]) for i in cat["items"])
    return f"""
    <section class="cat">
      <div class="cat-head" style="border-color:{cat["hue"]}">
        <div class="cat-dot" style="background:{cat["hue"]}"></div>
        <div class="cat-name">{cat["name"]}</div>
        <div class="cat-sub">{cat["sub"]}</div>
        <div class="cat-count">{n} SIGNAL{"S" if n != 1 else ""}</div>
      </div>
      {cards}
    </section>"""


def _foot(*_args) -> str:
    return ""


FOOTER_TEMPLATE = """
<div style="width:100%;font-family:'Helvetica',sans-serif;font-size:6.2pt;
  color:#6B7A90;padding:0 14mm;display:flex;justify-content:space-between;
  border-top:1px solid #C9D2DE;margin:0 0 6mm;padding-top:2mm;letter-spacing:.06em;">
  <span>THIS WEEK IN AI &middot; ISSUED {ISSUED}</span>
  <span>EVERY CLAIM CARRIES ITS SOURCE CLASS</span>
  <span class="pageNumber"></span>/<span class="totalPages"></span>
</div>"""


def build_html(data: dict) -> str:
    cats = data["categories"]
    glance = "".join(
        f"""<div class="gcell"><div class="gval">{g["value"]}<i>{g["unit"]}</i></div>
        <div class="glabel">{g["label"]}</div><div class="gnote">{g["note"]}</div></div>"""
        for g in data["glance"]
    )
    total_signals = sum(len(c["items"]) for c in cats)
    total_sources = sum(len(i["sources"]) for c in cats for i in c["items"])

    masthead = f"""
    <div class="masthead">
      <div class="mast-top">
        <div class="wordmark">This Week<br>in AI<span>Signal briefing</span></div>
        <div class="mast-meta">WEEK <b>{data["week"]}</b> &nbsp; {data["range"]}<br>
          <b>{total_signals}</b> signals kept &nbsp;·&nbsp; <b>{len(data["dropped"])}</b> dropped<br>
          <b>{total_sources}</b> sources &nbsp;·&nbsp; <b>{len(cats)}</b> categories</div>
      </div>
      <div class="thread-label">THE THREAD</div>
      <div class="thread">{data["thread"]}</div>
    </div>"""

    dropped = "".join(
        f"""<div class="drop"><div><div class="drop-t">{d["topic"]}</div>
        <div class="drop-r">{d["reason"]}</div></div>
        <div class="drop-v">{d["verdict"]}</div></div>"""
        for d in data["dropped"]
    )
    gates = "".join(
        f"""<tr><td class="g-st"><span>{"PASS" if g["pass"] else "FAIL"}</span></td>
        <td class="g-n">{g["name"]}</td><td class="g-v">{g["score"]}</td>
        <td class="g-d">{g["detail"]}</td></tr>"""
        for g in data["gates"]
    )
    legend = "".join(
        f'<div><i style="background:{c}"></i>{label}</div>'
        for c, label in SOURCE_CLASSES.values()
    )
    sections = "".join(_category(c) for c in cats)

    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{_fonts()}{CSS}</style></head><body>
{masthead}
<div class="glance">{glance}</div>
{sections}

<div class="panel">
  <div class="panel-h">What was dropped, and why</div>
  <div class="panel-lede">Four candidate stories were researched and cut before
    publication. A briefing that only shows what survived is hiding its own error
    rate, so the rejections are printed with their reasons.</div>
  {dropped}
</div>

<div class="panel">
  <div class="panel-h">Verification ledger</div>
  <div class="panel-lede">Five deterministic checks run on the assembled issue
    before it may publish. They are plain functions, not model judgement, and they
    are the reason no claim above appears without an attached source.</div>
  <table class="gates">{gates}</table>
  <div class="legend">{legend}</div>
</div>

<div class="panel">
  <div class="panel-h">How to read the source meter</div>
  <div class="panel-lede">Every card carries a strip of ticks, one per source,
    coloured by class. <b>Primary</b> is the originating document — a government
    order, a survey with published methodology. <b>Independent</b> is a newsroom
    doing its own reporting. <b>Vendor claim</b> is a company describing its own
    product or process, reported as a claim and never as a verified fact.
    <b>Conflicting</b> flags a source that disagrees with the others, printed
    rather than quietly resolved.<br><br>
    A grade of MEDIUM does not mean the story is doubtful. It means the strongest
    available source is a vendor, or the sources disagree on a detail, and you
    should check before acting on the specifics.</div>
</div>
</body></html>"""


def render_pdf(data_path: Path | str, out_path: Path | str | None = None) -> Path:
    from playwright.sync_api import sync_playwright

    data = json.loads(Path(data_path).read_text(encoding="utf-8"))
    out = Path(out_path) if out_path else OUTPUT_DIR / f"briefing-{data['issued']}.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)

    html_path = out.with_suffix(".html")
    html_path.write_text(build_html(data), encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(html_path.as_uri(), wait_until="networkidle")
        page.emulate_media(media="print")
        page.pdf(
            path=str(out),
            format="A4",
            print_background=True,
            display_header_footer=True,
            header_template="<div></div>",
            footer_template=FOOTER_TEMPLATE.replace("{ISSUED}", data["issued"]),
            prefer_css_page_size=True,
        )
        browser.close()
    return out
