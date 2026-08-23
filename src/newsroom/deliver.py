"""Delivery: who gets the edition, and when.

Recipients and send time live in ``recipients.toml``; credentials never do. The
SMTP password is read from the environment only, so the config file stays safe to
commit and safe to paste into a chat.

Sending is a separate command from building. A failed send should never destroy a
good edition, and a re-send should never require a re-run.
"""

from __future__ import annotations

import json
import mimetypes
import os
import smtplib
import ssl
import tomllib
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

from newsroom.config import ROOT
from newsroom.email_edition import build_email, build_plaintext

RECIPIENTS_PATH = ROOT / "recipients.toml"

# Common providers. Anything else: set host and port explicitly in the config.
PRESETS = {
    "gmail": ("smtp.gmail.com", 587),
    "outlook": ("smtp-mail.outlook.com", 587),
    "office365": ("smtp.office365.com", 587),
    "yahoo": ("smtp.mail.yahoo.com", 587),
    "zoho": ("smtp.zoho.com", 587),
    "fastmail": ("smtp.fastmail.com", 587),
}


def load_config() -> dict:
    if not RECIPIENTS_PATH.is_file():
        raise RuntimeError(
            f"{RECIPIENTS_PATH} not found — copy recipients.example.toml and fill it in."
        )
    with open(RECIPIENTS_PATH, "rb") as fh:
        return tomllib.load(fh)


def _smtp_settings(cfg: dict) -> tuple[str, int, str, str]:
    smtp = cfg.get("smtp", {})
    provider = smtp.get("provider", "").lower()
    if provider in PRESETS:
        host, port = PRESETS[provider]
    else:
        host, port = smtp.get("host", ""), int(smtp.get("port", 587))
    if not host:
        raise RuntimeError(
            "No SMTP host. Set [smtp] provider to one of "
            f"{', '.join(PRESETS)} or give host and port explicitly."
        )

    user = smtp.get("username") or cfg["sender"]["address"]
    env_var = smtp.get("password_env", "NEWSROOM_SMTP_PASSWORD")
    password = os.environ.get(env_var, "")
    if not password:
        raise RuntimeError(
            f"No password in ${env_var}. Export it before sending — it is "
            "deliberately not read from the config file.\n"
            "  Gmail and Yahoo require an app password, not your login password."
        )
    return host, port, user, password


def build_message(
    data: dict,
    cfg: dict,
    recipient: dict,
    *,
    pdf_path: Path | None = None,
    web_url: str = "",
) -> EmailMessage:
    sender = cfg["sender"]
    subject = cfg.get("subject_template", "This Week in AI — Edition {week}").format(
        week=data["week"], range=data["range"], issued=data["issued"]
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((sender.get("name", "This Week in AI"), sender["address"]))
    msg["To"] = formataddr((recipient.get("name", ""), recipient["address"]))
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender["address"].split("@")[-1])
    if reply_to := sender.get("reply_to"):
        msg["Reply-To"] = reply_to
    # One-click unsubscribe: expected by Gmail and Yahoo for bulk senders, and
    # the difference between the inbox and the spam folder at any volume.
    if unsub := cfg.get("unsubscribe_mailto"):
        msg["List-Unsubscribe"] = f"<mailto:{unsub}?subject=unsubscribe>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg["List-Id"] = f"This Week in AI <{sender['address'].replace('@', '.')}>"

    extras = {
        "recipient_name": recipient.get("name", ""),
        "greeting": recipient.get("greeting", "") or cfg.get("greeting", ""),
        "author": cfg.get("author", ""),
        "github_url": cfg.get("github_url", ""),
    }
    msg.set_content(build_plaintext(data, web_url, **extras))
    msg.add_alternative(build_email(data, web_url, **extras), subtype="html")

    if pdf_path and Path(pdf_path).is_file():
        blob = Path(pdf_path).read_bytes()
        ctype, _ = mimetypes.guess_type(str(pdf_path))
        maintype, _, subtype = (ctype or "application/pdf").partition("/")
        msg.add_attachment(
            blob,
            maintype=maintype,
            subtype=subtype,
            filename=f"this-week-in-ai-{data['issued']}.pdf",
        )
    return msg


def send(
    data_path: Path | str,
    *,
    pdf_path: Path | None = None,
    dry_run: bool = False,
) -> int:
    data = json.loads(Path(data_path).read_text(encoding="utf-8"))
    cfg = load_config()
    web_url = cfg.get("web_url", "").format(issued=data["issued"], week=data["week"])
    people = [r for r in cfg.get("recipients", []) if r.get("active", True)]

    if not people:
        print("No active recipients.")
        return 1

    if dry_run:
        print(f"DRY RUN — edition {data['week']}, {len(people)} recipient(s)")
        for r in people:
            print(f"  would send to {r['address']}")
        msg = build_message(data, cfg, people[0], pdf_path=pdf_path, web_url=web_url)
        print(f"\n  Subject: {msg['Subject']}")
        print(f"  From:    {msg['From']}")
        print(f"  Parts:   {[p.get_content_type() for p in msg.walk()]}")
        return 0

    host, port, user, password = _smtp_settings(cfg)
    sent, failed = 0, []
    context = ssl.create_default_context()

    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls(context=context)
        server.login(user, password)
        for person in people:
            try:
                server.send_message(
                    build_message(
                        data, cfg, person, pdf_path=pdf_path, web_url=web_url
                    )
                )
                print(f"  sent  {person['address']}")
                sent += 1
            except Exception as exc:  # one bad address must not stop the run
                print(f"  FAIL  {person['address']}: {exc}")
                failed.append(person["address"])

    print(f"\n  {sent} sent, {len(failed)} failed")
    return 0 if not failed else 1


def cron_line() -> str:
    """The crontab entry implied by the configured schedule."""
    cfg = load_config()
    sched = cfg.get("schedule", {})
    day = str(sched.get("weekday", "SUN")).upper()[:3]
    hour, minute = int(sched.get("hour", 8)), int(sched.get("minute", 0))
    tz = sched.get("timezone", "Asia/Kolkata")
    python = "python3"
    return (
        f"# This Week in AI — every {day} at {hour:02d}:{minute:02d} {tz}\n"
        f"CRON_TZ={tz}\n"
        f"{minute} {hour} * * {day} cd {ROOT} && "
        f"{python} -m newsroom.run && {python} -m newsroom.run --send\n"
    )
