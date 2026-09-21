#!/usr/bin/env python3
"""LeadFinder v3.5 — scan entry point."""
from __future__ import annotations
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from config import Config
from models import Lead, classify_tier
from filters.gates import quality_gate
from classifiers.niche import detect_niche
from classifiers.tier import classify
from outreach.generator import generate as gen_outreach
from notifiers.telegram import send_new_leads
from db import DB
from sources.reddit import scan as reddit_scan
from sources.hackernews import scan as hn_scan
from sources.bitcointalk import scan as bt_scan

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("leadfinder")
cfg = Config()
db = DB()


def gather() -> list[Lead]:
    leads, seen = [], set()
    log.info("scanning Reddit...")
    for l in reddit_scan(cfg):
        if l.url and l.url not in seen: seen.add(l.url); leads.append(l)
    log.info("scanning HN...")
    for l in hn_scan(cfg):
        if l.url and l.url not in seen: seen.add(l.url); leads.append(l)
    log.info("scanning Bitcointalk...")
    for l in bt_scan(cfg):
        if l.url and l.url not in seen: seen.add(l.url); leads.append(l)
    return leads


def filter_score(leads: list[Lead]) -> list[Lead]:
    max_age = cfg.scanner.get("max_age_hours", 72)
    min_budget = cfg.scanner.get("min_budget_usd", 5.0)
    kept = []
    for l in leads:
        passes, score, budget, pay = quality_gate(l, max_age, min_budget)
        if not passes: continue
        l.score = score
        l.budget_signals = list(dict.fromkeys(budget))
        l.payment_signals = list(dict.fromkeys(pay))
        l.niche = detect_niche(f"{l.title}\n{l.snippet}")
        l.tier = classify(l.budget_signals)
        l.outreach_draft = gen_outreach(l, l.niche, cfg)
        kept.append(l)
    # Crosspost dedup
    seen_titles = set()
    final = []
    for l in kept:
        norm = "".join(c.lower() for c in l.title if c.isalnum())[:80]
        if norm in seen_titles: continue
        seen_titles.add(norm)
        final.append(l)
    final.sort(key=lambda x: (-x.score, -x.created_utc))
    return final


def main():
    log.info("=== LeadFinder v3.5 scan starting ===")
    start = time.time()
    raw = gather()
    log.info("gathered %d raw leads", len(raw))
    final = filter_score(raw)
    log.info("%d leads passed gates", len(final))
    db.save_leads([l.as_dict() for l in final])
    # Add to pipeline
    for l in final:
        db.upsert_pipe(l.url, l.title, l.source, l.score)
    sent = send_new_leads(cfg, db)
    elapsed = time.time() - start
    log.info("done in %.1fs — %d leads, %d sent to Telegram", elapsed, len(final), sent)
    print(f"\n=== {len(final)} leads found, {sent} sent to Telegram ===")
    for l in final[:10]:
        age = f"{l.age_hours:.0f}h" if l.created_utc else "?"
        print(f"  [{l.score:3d}] {l.source:22s} [{age:>4}] ({l.niche:8s}) [{l.tier:11s}] {l.title[:50]}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        log.error("FATAL: %s", e)
        log.error(traceback.format_exc())
        try:
            import urllib.request, urllib.parse, re
            token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
            chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
            if token and chat_id:
                err = re.sub(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b", "[REDACTED]", str(e))[:500]
                msg = f'🚨 <b>Scan CRASHED</b>\n<pre>{escape_html(err)}</pre>'
                payload = urllib.parse.urlencode({"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}).encode()
                urllib.request.urlopen(urllib.request.Request(
                    f"https://api.telegram.org/bot{token}/sendMessage", data=payload, method="POST"), timeout=15).read()
        except: pass
        sys.exit(1)
