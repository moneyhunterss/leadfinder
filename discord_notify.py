"""Discord webhook notifier — sends new leads to a Discord channel.

Reads env vars:
    DISCORD_WEBHOOK_URL   (required) — from Discord: Edit Channel → Integrations → Webhooks → New Webhook → Copy URL

Usage:
    python discord_notify.py \\
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
import urllib.request
import urllib.parse
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("discord")


def send_message(webhook_url: str, payload: dict) -> bool:
    """Send a single Discord webhook message. Returns True on success."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status in (200, 204)
    except Exception as e:
        log.warning("discord send failed: %s", e)
        return False


def format_embed(lead: dict) -> dict:
    """Build a Discord embed for a lead."""
    title = (lead.get("title") or "")[:256]
    url = lead.get("url", "")
    source = lead.get("source", "")
    score = lead.get("score", 0)
    budget = ", ".join(lead.get("budget_signals", [])) or "—"
    payment = ", ".join(lead.get("payment_signals", [])) or "—"
    snippet = (lead.get("snippet") or "")[:500].replace("\n", " ")
    outreach = (lead.get("outreach_draft") or "")[:1500]

    # Color by score
    color = 0x00FF00 if score >= 80 else 0xFFFF00 if score >= 60 else 0xFFA500

    fields = [
        {"name": "Source", "value": f"`{source}`", "inline": True},
        {"name": "Budget", "value": budget, "inline": True},
        {"name": "Payment", "value": payment, "inline": True},
    ]
    if snippet:
        fields.append({"name": "Post body", "value": snippet[:1024], "inline": False})
    if outreach:
        fields.append({"name": "Draft outreach (copy & paste)", "value": f"```\n{outreach[:1024]}\n```", "inline": False})

    return {
        "embeds": [{
            "title": f"[{score}] {title}",
            "url": url,
            "color": color,
            "fields": fields,
            "footer": {"text": "LeadFinder v2"},
        }]
    }


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

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not args.dry_run and not webhook_url:
        log.error("DISCORD_WEBHOOK_URL env var must be set")
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
        msg = f"💤 No new leads above score {args.min_score} this run. ({len(curr)} tracked total)"
        if args.dry_run:
            print(msg)
        else:
            send_message(webhook_url, {"content": msg})
        return

    sent = 0
    for lead in new_leads[: args.max_messages]:
        payload = format_embed(lead)
        if args.dry_run:
            print("=" * 60)
            print(json.dumps(payload, indent=2))
        else:
            ok = send_message(webhook_url, payload)
            if ok:
                sent += 1
            time.sleep(1)

    log.info("sent %d/%d messages", sent, len(new_leads[: args.max_messages]))


if __name__ == "__main__":
    main()
