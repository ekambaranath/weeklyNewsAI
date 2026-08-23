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
import re
import smtplib
import ssl
import subprocess
import tomllib
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

from newsroom.config import ROOT
from newsroom.email_edition import build_email, build_plaintext

RECIPIENTS_PATH = ROOT / "recipients.toml"

PRESETS = {
    "gmail": ("smtp.gmail.com", 587),
    "outlook": ("smtp-mail.outlook.com", 587),
    "office365": ("smtp.office365.com", 587),
    "yahoo": ("smtp.mail.yahoo.com", 587),
    "zoho": ("smtp.zoho.com", 587),
    "fastmail": ("smtp.fastmail.com", 587),
}


def redact(address: str) -> str:
    """Mask an address for console output and logs."""
    local, _, domain = address.partition("@")
    if len(local) <= 2:
        shown = local[:1] + "*"
    else:
        shown = f"{local[0]}{'*' * (len(local) - 2)}{local[-1]}"
    return f"{shown}@{domain}"


def preflight(verbose: bool = False) -> list[str]:
    """Refuse to send if recipient addresses could reach the repository."""
    problems: list[str] = []

    def git(*args: str) -> str:
        try:
            return subprocess.run(
                ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""

    def note(msg: str) -> None:
        if verbose:
            print(f"    {msg}")

    note(f"repo root: {ROOT}")
    if not (ROOT / ".git").exists():
        note("no .git directory — nothing can leak")
        return problems

    note(f"tracked files: {len(git('ls-files').splitlines())}")
    if git("ls-files", "--error-unmatch", "recipients.toml"):
        problems.append(
            "recipients.toml is TRACKED by git. Run:\n"
            "      git rm --cached recipients.toml && git commit -m 'untrack recipients'"
        )
    if git("log", "--all", "--oneline", "--", "recipients.toml"):
        problems.append(
            "recipients.toml appears in git HISTORY. Deleting it now is not enough — "
            "the addresses remain in every clone. Purge with git-filter-repo, then "
            "force-push, and treat the addresses as disclosed."
        )

    tracked = [f for f in git("ls-files").splitlines() if f.endswith((".py", ".toml", ".md"))]
    pattern = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
    for rel in tracked:
        path = ROOT / rel
        if not path.is_file() or "example" in rel:
            continue
        try:
            found = {
                a
                for a in pattern.findall(path.read_text(encoding="utf-8", errors="ignore"))
                if not a.endswith(("example.com", "example.org"))
            }
        except OSError:
            continue
        if found:
            problems.append(f"{rel} contains real address(es): {sorted(found)}")
    note(f"scanned {len(tracked)} tracked .py/.toml/.md files for addresses")
    note(f"result: {len(problems)} problem(s)")
    return problems


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

    if not recipient.get("address"):
        raise ValueError("recipient has no address")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((sender.get("name", "This Week in AI"), sender["address"]))
    msg["To"] = formataddr((recipient.get("name", ""), recipient["address"]))
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender["address"].split("@")[-1])
    if reply_to := sender.get("reply_to"):
        msg["Reply-To"] = reply_to
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

    # One recipient per message. No CC, no BCC, no comma-joined To — nobody in
    # this list learns who else is on it.
    assert msg["To"].count("@") == 1, "message addressed to more than one person"
    assert msg["Cc"] is None and msg["Bcc"] is None, "CC/BCC must never be set"

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
    problems = preflight()
    if problems:
        print("REFUSING TO SEND — recipient addresses are exposed:\n")
        for issue in problems:
            print(f"  ! {issue}")
        return 2

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
            print(f"  would send to {redact(r['address'])}  (individual message)")
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
                print(f"  sent  {redact(person['address'])}")
                sent += 1
            except Exception as exc:  # one bad address must not stop the run
                print(f"  FAIL  {redact(person['address'])}: {exc}")
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
