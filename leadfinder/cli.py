"""LeadFinder CLI.

Usage:
    python -m leadfinder scan           # one-shot scan, print + store
    python -m leadfinder watch --interval 20
    python -m leadfinder export --format md|csv|json
    python -m leadfinder stats
    python -m leadfinder outreach --limit 20
"""
from __future__ import annotations
import argparse
import logging
import time
from pathlib import Path

import yaml

from .filters import Lead, score_lead
from .store import Store
from .exporters import print_table, to_markdown, to_json, to_csv
from .outreach import generate_draft
from .sources import reddit, hackernews, bitcointalk, laborx, gitcoin, cryptotask

log = logging.getLogger("leadfinder")

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "leads.db"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def gather_leads(cfg: dict) -> list[Lead]:
    """Run all enabled sources and return a flat list of raw leads."""
    srcs = cfg["sources"]
    anon = cfg
    leads: list[Lead] = []
    if srcs["reddit"]["enabled"]:
        leads += reddit.scan(srcs["reddit"], anon)
    if srcs["hackernews"]["enabled"]:
        leads += hackernews.scan(srcs["hackernews"], anon)
    if srcs["bitcointalk"]["enabled"]:
        leads += bitcointalk.scan(srcs["bitcointalk"], anon)
    if srcs["laborx"]["enabled"]:
        leads += laborx.scan(srcs["laborx"], anon)
    if srcs["gitcoin"]["enabled"]:
        leads += gitcoin.scan(srcs["gitcoin"], anon)
    if srcs["cryptotask"]["enabled"]:
        leads += cryptotask.scan(srcs["cryptotask"], anon)
    return leads


def filter_and_score(leads: list[Lead], cfg: dict) -> list[Lead]:
    flt = cfg["filters"]
    min_score = cfg.get("min_score", 30)
    max_age = cfg.get("max_age_hours", 168)
    for l in leads:
        text = f"{l.title}\n{l.snippet}".strip()
        s, budget_hits, pay_hits = score_lead(
            text,
            whitelist=flt["keyword_whitelist"],
            blacklist=flt["keyword_blacklist"],
            payment_signals=flt["payment_signals"],
            flair=l.flair,
            created_utc=l.created_utc,
            max_age_hours=max_age,
        )
        l.score = s
        l.budget_signals = budget_hits
        l.payment_signals = pay_hits
    return [l for l in leads if l.score >= min_score]


def add_outreach(leads: list[Lead], cfg: dict) -> None:
    if not cfg.get("outreach", {}).get("enabled", True):
        return
    tone = cfg["outreach"].get("tone", "direct")
    max_words = cfg["outreach"].get("max_words", 80)
    include_pp = cfg["outreach"].get("include_pricing_prompt", True)
    for l in leads:
        l.outreach_draft = generate_draft(l, tone=tone, max_words=max_words, include_pricing_prompt=include_pp)


def cmd_scan(args, cfg):
    raw = gather_leads(cfg)
    log.info("gathered %d raw leads", len(raw))
    filtered = filter_and_score(raw, cfg)
    add_outreach(filtered, cfg)
    store = Store(DB_PATH)
    new = store.upsert_many(filtered)
    log.info("stored %d leads (%d new)", len(filtered), len(new))
    all_leads = store.all(min_score=cfg.get("min_score", 30), limit=50)
    print_table(all_leads, limit=50)
    # Also dump fresh digest to download/
    digest = to_markdown(all_leads, title="LeadFinder scan digest")
    out_dir = Path("/home/z/my-project/download")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "leads_digest.md").write_text(digest, encoding="utf-8")
    (out_dir / "leads.json").write_text(to_json(all_leads), encoding="utf-8")
    (out_dir / "leads.csv").write_text(to_csv(all_leads), encoding="utf-8")
    log.info("digest -> %s", out_dir / "leads_digest.md")


def cmd_watch(args, cfg):
    interval = args.interval
    log.info("watch mode every %d min — Ctrl+C to stop", interval)
    store = Store(DB_PATH)
    try:
        while True:
            raw = gather_leads(cfg)
            filtered = filter_and_score(raw, cfg)
            add_outreach(filtered, cfg)
            new = store.upsert_many(filtered)
            log.info("tick: %d gathered, %d filtered, %d new", len(raw), len(filtered), len(new))
            if new:
                print_table(new, limit=10)
            time.sleep(interval * 60)
    except KeyboardInterrupt:
        log.info("stopping watch")


def cmd_export(args, cfg):
    store = Store(DB_PATH)
    leads = store.all(min_score=cfg.get("min_score", 30))
    out_dir = Path("/home/z/my-project/download")
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.format == "md":
        (out_dir / "leads_digest.md").write_text(to_markdown(leads), encoding="utf-8")
    elif args.format == "json":
        (out_dir / "leads.json").write_text(to_json(leads), encoding="utf-8")
    elif args.format == "csv":
        (out_dir / "leads.csv").write_text(to_csv(leads), encoding="utf-8")
    log.info("exported %d leads to %s/leads.%s", len(leads), out_dir, args.format)


def cmd_stats(args, cfg):
    store = Store(DB_PATH)
    by_src = store.count_by_source()
    print(f"Total leads stored: {sum(by_src.values())}")
    for s, n in sorted(by_src.items(), key=lambda x: -x[1]):
        print(f"  {s:35s} {n:5d}")


def cmd_outreach(args, cfg):
    store = Store(DB_PATH)
    leads = store.all(min_score=cfg.get("min_score", 30), limit=args.limit)
    for l in leads:
        print(f"\n--- [{l.score}] {l.title}")
        print(f"URL: {l.url}")
        print(f"Draft:\n{l.outreach_draft}\n")


def main():
    ap = argparse.ArgumentParser(prog="leadfinder")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan")
    w = sub.add_parser("watch")
    w.add_argument("--interval", type=int, default=20)
    e = sub.add_parser("export")
    e.add_argument("--format", choices=["md", "csv", "json"], default="md")
    sub.add_parser("stats")
    o = sub.add_parser("outreach")
    o.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    cfg = load_config()
    {"scan": cmd_scan, "watch": cmd_watch, "export": cmd_export,
     "stats": cmd_stats, "outreach": cmd_outreach}[args.cmd](args, cfg)


if __name__ == "__main__":
    main()
