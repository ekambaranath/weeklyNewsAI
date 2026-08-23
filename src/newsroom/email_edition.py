"""The email edition.

A separate build, not a squeezed copy of the web one. Mail clients are a hostile
rendering target: Outlook uses Word's engine, Gmail strips `<style>` blocks in
some views, nobody runs JavaScript, web fonts are unreliable, and CSS grid and
flex are unusable. So this edition is nested tables with inline styles, one
600px column, system fonts, and no animation.

Editorially that constraint is useful. Email is the *trailer*, not the feature:
the thread, the four numbers, each headline with its confidence grade and its
single most decision-relevant line, and a clear route to the full edition. The
animated explainers, the charts and the full field grid live on the web; the PDF
rides along as an attachment for the archive.

The design carries over the two things that make the paper what it is — category
colour coding and the confidence grade — because those are what let someone
triage the week from the inbox without opening anything.
"""

from __future__ import annotations

import json
from pathlib import Path

from newsroom.config import OUTPUT_DIR
from newsroom.render import CONFIDENCE

INK = "#101B2D"
PAPER = "#F2F4F7"
RULE = "#C9D2DE"
MUTED = "#6B7A90"
BODY = "#3C4A60"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
MONO = "'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace"


def _px(n: int) -> str:
    return f"{n}px"


def build_email(
    data: dict,
    web_url: str = "",
    *,
    recipient_name: str = "",
    greeting: str = "",
    author: str = "",
    github_url: str = "",
) -> str:
    """One message per recipient, addressed to them by name.

    The greeting is deliberately part of the HTML rather than a separate note:
    a newsletter that opens cold reads like a blast, and this one is going to
    people who know the sender.
    """
    cats = data["categories"]
    signals = sum(len(c["items"]) for c in cats)
    sources = sum(len(i["sources"]) for c in cats for i in c["items"])

    # ---- the four numbers, two per row so they survive a narrow viewport
    cells = []
    for g in data["glance"]:
        cells.append(
            f"""<td class="stack" width="50%" valign="top" style="padding:0 12px 18px 0;">
              <div style="font:700 30px/1 {FONT};color:#fff;letter-spacing:-.5px;">
                {g["value"]}<span style="font-size:14px;color:#8FA6C4;">{g["unit"]}</span></div>
              <div style="font:600 12px/1.35 {FONT};color:#fff;padding-top:6px;">{g["label"]}</div>
              <div style="font:400 10px/1.45 {MONO};color:#7E9ABE;padding-top:4px;">{g["note"]}</div>
            </td>"""
        )
    glance_rows = "".join(
        f"<tr>{cells[i]}{cells[i + 1] if i + 1 < len(cells) else '<td></td>'}</tr>"
        for i in range(0, len(cells), 2)
    )

    # ---- one block per story: kicker, headline, dek, the actionable line, grade
    blocks = []
    for cat in cats:
        for item in cat["items"]:
            fields = item["fields"]
            # The last field is always the "so what" — that is what email carries.
            key = list(fields)[-1]
            conf = item["confidence"]
            strong = sum(
                1 for s in item["sources"] if s["cls"] in ("primary", "independent")
            )
            blocks.append(
                f"""
<tr><td style="padding:0 0 10px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
    style="background:#ffffff;border:1px solid {RULE};border-left:4px solid {cat["hue"]};">
    <tr><td class="pad" style="padding:20px 22px;">
      <div style="font:600 10px/1 {MONO};letter-spacing:1.6px;text-transform:uppercase;
        color:{cat["hue"]};padding-bottom:8px;">{cat["name"]}</div>
      <div style="font:700 21px/1.18 {FONT};color:{INK};letter-spacing:-.3px;
        padding-bottom:8px;">{item["headline"]}</div>
      <div style="font:400 15px/1.5 {FONT};color:{BODY};padding-bottom:14px;">
        {item["dek"]}</div>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
        style="border-top:1px solid #E3E8EF;">
        <tr><td style="padding:12px 0 0;">
          <div style="font:400 10px/1 {MONO};letter-spacing:1.2px;text-transform:uppercase;
            color:{MUTED};padding-bottom:5px;">{key}</div>
          <div style="font:400 14px/1.5 {FONT};color:{INK};">{fields[key]}</div>
        </td></tr>
      </table>
      <table role="presentation" cellpadding="0" cellspacing="0" border="0"
        style="padding-top:14px;"><tr>
        <td style="background:{CONFIDENCE[conf]};padding:5px 9px;
          font:600 10px/1 {MONO};letter-spacing:1.2px;color:#ffffff;">{conf} CONFIDENCE</td>
        <td style="padding-left:12px;font:400 10px/1 {MONO};color:{MUTED};letter-spacing:.6px;">
          {strong}/{len(item["sources"])} PRIMARY OR INDEPENDENT</td>
      </tr></table>
    </td></tr>
  </table>
</td></tr>"""
            )

    dropped = "".join(
        f"""<tr><td style="padding:8px 0;border-bottom:1px solid #E3E8EF;">
          <span style="font:600 13px/1.4 {FONT};color:{INK};">{d["topic"]}</span><br>
          <span style="font:400 12px/1.45 {FONT};color:{MUTED};">{d["verdict"]}</span>
        </td></tr>"""
        for d in data["dropped"]
    )

    # ---- personal note, above the fold
    first = (recipient_name or "").strip().split(" ")[0]
    hello = f"Hi {first}," if first else "Hi,"
    note = greeting or (
        f"This is a weekly AI newspaper {('built by ' + author) if author else 'I built'} "
        "— it gathers the week's AI news, verifies every claim against its source, "
        "and prints what it had to throw away. The full edition is attached as a PDF."
    )
    repo_line = ""
    if github_url:
        repo_line = (
            f'<div style="font:400 13px/1.55 {FONT};color:{BODY};padding-top:10px;">'
            f'The whole thing is open source — agents, verification gates and all: '
            f'<a href="{github_url}" style="color:{INK};font-weight:600;">{github_url}</a></div>'
        )
    greeting_block = f"""
<tr><td style="padding:0 0 14px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
    style="background:#FFFDF7;border:1px solid #E8DCBF;border-top:3px solid #8A6100;">
    <tr><td class="pad" style="padding:20px 22px;">
      <div style="font:600 17px/1.4 {FONT};color:{INK};padding-bottom:8px;">{hello}</div>
      <div style="font:400 14px/1.6 {FONT};color:{BODY};">{note}</div>
      {repo_line}
    </td></tr>
  </table>
</td></tr>"""

    cta = ""
    if web_url:
        cta = f"""
    <tr><td align="center" style="padding:6px 0 22px;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
        <td style="background:{INK};">
          <a href="{web_url}" style="display:inline-block;padding:14px 30px;
            font:600 14px/1 {FONT};color:#ffffff;text-decoration:none;letter-spacing:.3px;">
            Read the full edition &nbsp;&rarr;</a></td>
      </tr></table>
      <div style="font:400 11px/1.6 {MONO};color:{MUTED};padding-top:10px;">
        Animated explainers, charts and every source &middot; PDF attached</div>
    </td></tr>"""

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light only">
<meta name="supported-color-schemes" content="light only">
<title>This Week in AI — Edition {data["week"]}</title>
<style>
  /* Outlook needs width="600" as an attribute; every other client honours this
     and reflows on a phone. Belt and braces, which is the norm in email. */
  @media only screen and (max-width:620px) {{
    .shell {{ width:100% !important; }}
    .pad {{ padding-left:18px !important; padding-right:18px !important; }}
    .stack {{ display:block !important; width:100% !important;
              padding:0 0 16px 0 !important; }}
    .bighead {{ font-size:32px !important; }}
  }}
</style>
<!--[if mso]><style>body,table,td{{font-family:Arial,Helvetica,sans-serif !important;}}</style><![endif]-->
</head>
<body style="margin:0;padding:0;background:{PAPER};-webkit-text-size-adjust:100%;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">
  {data["thread"][:140]}&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;
</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
  style="background:{PAPER};"><tr><td align="center" style="padding:24px 12px;">

<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"
  class="shell" style="width:600px;max-width:100%;">

  <tr><td class="pad" style="background:{INK};padding:30px 26px 24px;">
    <div class="bighead" style="font:700 40px/.92 {FONT};color:#ffffff;
      letter-spacing:-1.2px;text-transform:uppercase;">This Week<br>in AI</div>
    <div style="font:400 10px/1 {MONO};letter-spacing:4px;color:#8FA6C4;padding-top:12px;">
      WEEKLY SIGNAL BRIEFING</div>
    <div style="border-top:1px solid rgba(255,255,255,.2);margin:18px 0 16px;"></div>
    <div style="font:400 11px/1.9 {MONO};color:#8FA6C4;">
      EDITION <b style="color:#fff;">{data["week"]}</b> &nbsp;&middot;&nbsp; {data["range"]}<br>
      <b style="color:#fff;">{signals}</b> signals &nbsp;&middot;&nbsp;
      <b style="color:#fff;">{len(data["dropped"])}</b> dropped &nbsp;&middot;&nbsp;
      <b style="color:#fff;">{sources}</b> sources</div>
    <div style="font:400 10px/1 {MONO};letter-spacing:2.6px;color:#7E9ABE;padding:20px 0 9px;">
      THE THREAD</div>
    <div style="font:400 16px/1.52 {FONT};color:#E7EEF6;">{data["thread"]}</div>
  </td></tr>

  <tr><td class="pad" style="background:{INK};padding:6px 26px 8px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
      style="border-top:2px solid rgba(255,255,255,.25);padding-top:18px;">
      {glance_rows}
    </table>
  </td></tr>

  {greeting_block}
  {"".join(blocks)}
  {cta}

  <tr><td class="pad" style="background:#ffffff;border:1px solid {RULE};padding:20px 22px;">
    <div style="font:700 15px/1.3 {FONT};color:{INK};text-transform:uppercase;
      letter-spacing:.6px;padding-bottom:6px;">Dropped this week</div>
    <div style="font:400 13px/1.5 {FONT};color:{BODY};padding-bottom:10px;">
      Researched, then cut. A paper that prints only what survived is hiding its
      own error rate.</div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
      {dropped}</table>
  </td></tr>

  <tr><td style="padding:22px 4px 0;border-top:2px solid {INK};margin-top:20px;">
    <div style="font:400 10px/1.8 {MONO};color:{MUTED};letter-spacing:1px;">
      THIS WEEK IN AI &middot; EDITION {data["week"]} &middot; ISSUED {data["issued"]}<br>
      ASSEMBLED LOCALLY &middot; NO API COST &middot; EVERY CLAIM CARRIES ITS SOURCE CLASS</div>
  </td></tr>

</table>
</td></tr></table>
</body></html>"""


def render_email(
    data_path: Path | str,
    web_url: str = "",
    out_path: Path | str | None = None,
    **kwargs,
) -> Path:
    data = json.loads(Path(data_path).read_text(encoding="utf-8"))
    out = Path(out_path) if out_path else OUTPUT_DIR / f"email-{data['issued']}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_email(data, web_url, **kwargs), encoding="utf-8")
    return out


def build_plaintext(
    data: dict,
    web_url: str = "",
    *,
    recipient_name: str = "",
    greeting: str = "",
    author: str = "",
    github_url: str = "",
) -> str:
    """The text/plain alternative. Required, not optional.

    A multipart message without one is scored as spam by several providers, and
    some readers only ever see this part.
    """
    first = (recipient_name or "").strip().split(" ")[0]
    note = greeting or (
        f"This is a weekly AI newspaper {('built by ' + author) if author else 'I built'} "
        "— it gathers the week's AI news, verifies every claim against its source, "
        "and prints what it had to throw away. The full edition is attached as a PDF."
    )
    lines = [
        f"Hi {first}," if first else "Hi,",
        "",
        note,
        "",
    ]
    if github_url:
        lines += [f"Open source: {github_url}", ""]
    lines += [
        "THIS WEEK IN AI",
        f"Edition {data['week']} — {data['range']}",
        "=" * 58,
        "",
        data["thread"],
        "",
        "-" * 58,
        "AT A GLANCE",
    ]
    for g in data["glance"]:
        lines.append(f"  {g['value']}{g['unit']} — {g['label']} ({g['note']})")
    lines += ["", "-" * 58, ""]

    for cat in data["categories"]:
        for item in cat["items"]:
            key = list(item["fields"])[-1]
            lines += [
                f"[{cat['name'].upper()}]  {item['headline']}",
                f"  {item['dek']}",
                f"  {key.upper()}: {item['fields'][key]}",
                f"  Confidence: {item['confidence']}",
                "",
            ]

    lines += ["-" * 58, "DROPPED THIS WEEK"]
    for d in data["dropped"]:
        lines.append(f"  {d['topic']} — {d['verdict']}")
    if web_url:
        lines += ["", f"Full edition: {web_url}"]
    lines += ["", f"Issued {data['issued']}. Assembled locally, no API cost."]
    return "\n".join(lines)
