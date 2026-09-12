"""Telegram notifier — sends new high-score leads to a Telegram chat (HTML mode).

Reads env vars:
    TELEGRAM_BOT_TOKEN   (required)
    TELEGRAM_CHAT_ID     (required)

Reads previous leads.json (prev-state) and current leads.json (curr-state),
sends one message per NEW lead above the score threshold.

Usage:
    python notify_telegram.py \\
        --prev-state data/leads_prev.json \\
        --curr-state data/leads.json \\
        --min-score 40
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("telegram")


def escape_html(text) -> str:
    if text is None:
        return ""
    return (str(text).replace("&", "&amp;")
                     .replace("<", "&lt;")
                     .replace(">", "&gt;"))


def send_message(bot_token: str, chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "false",
    }).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=payload, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
        if not resp.get("ok"):
            # Fallback: plain text
            payload = urllib.parse.urlencode({
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": "false",
            }).encode("utf-8")
            req = urllib.request.Request(url, data=payload, method="POST")
            with urllib.request.urlopen(req, timeout=15) as r:
                resp = json.loads(r.read())
        return resp.get("ok", False)
    except Exception as e:
        log.warning("telegram send failed: %s", e)
        return False


def format_lead(lead: dict) -> str:
    """HTML-formatted lead message — handles brackets safely."""
    title = escape_html((lead.get("title") or "")[:120])
    url = lead.get("url", "")
    source = escape_html(lead.get("source", ""))
    score = lead.get("score", 0)
    budget = escape_html(", ".join(lead.get("budget_signals", [])) or "—")
    payment = escape_html(", ".join(lead.get("payment_signals", [])) or "—")
    snippet = escape_html((lead.get("snippet") or "")[:280].replace("\n", " "))
    outreach = escape_html(lead.get("outreach_draft") or "")

    msg = (
        f"<b>[{score}] {title}</b>\n"
        f"<code>{source}</code>\n\n"
        f"<b>URL:</b> {url}\n"
        f"<b>Budget:</b> {budget}\n"
        f"<b>Payment:</b> {payment}\n"
    )
    if snippet:
        msg += f"\n<i>{snippet}</i>\n"
    if outreach:
        msg += f"\n<b>Reply text (copy & paste):</b>\n<pre>{outreach}</pre>\n"
    return msg


def load_state(path: str | None) -> dict[str, dict]:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
        return {item["url"]: item for item in data if "url" in item}
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prev-state", default="data/leads_prev.json")
    ap.add_argument("--curr-state", default="data/leads.json")
    ap.add_argument("--min-score", type=int, default=40)
    ap.add_argument("--max-messages", type=int, default=20)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not args.dry_run and (not bot_token or not chat_id):
        log.error("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID env vars must be set")
        sys.exit(1)

    prev = load_state(args.prev_state)
    curr = load_state(args.curr_state)
    if not curr:
        log.error("no current leads found at %s", args.curr_state)
        sys.exit(1)

    new_urls = [u for u in curr if u not in prev]
    new_leads = [curr[u] for u in new_urls if curr[u].get("score", 0) >= args.min_score]
    new_leads.sort(key=lambda x: -x.get("score", 0))

    log.info("prev=%d curr=%d new_above_%d=%d", len(prev), len(curr), args.min_score, len(new_leads))

    if not new_leads:
        msg = f"<i>No new leads above score {args.min_score} this run. ({len(curr)} tracked total.)</i>"
        if args.dry_run:
            print(msg)
        else:
            send_message(bot_token, chat_id, msg)
        return

    sent = 0
    for lead in new_leads[: args.max_messages]:
        msg = format_lead(lead)
        if args.dry_run:
            print("=" * 60)
            print(msg)
        else:
            ok = send_message(bot_token, chat_id, msg)
            if ok:
                sent += 1
            time.sleep(1)

    if not args.dry_run:
        log.info("sent %d/%d messages", sent, len(new_leads[: args.max_messages]))


if __name__ == "__main__":
    main()
