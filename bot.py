#!/usr/bin/env python3
"""LeadFinder Telegram bot — 300IQ edition.

Long-polling bot with full pipeline tracking, live settings, niche filters,
earnings tracking, daily/weekly digests.

Commands:
    /start            — register, show chat_id
    /help             — list all commands
    /scan             — run fresh scan, send top 5 new leads
    /leads [N]        — top N leads from last scan (default 10)
    /stats            — counts by source + score band + niche
    /niche <name>     — filter leads by niche (writing/dev/design/video/data/va/crypto/translation/audio/marketing)
    /convert <url> <status> [notes]  — move lead through pipeline
                          status: new|contacted|replied|quoted|in_progress|paid|rejected|ghosted
    /paid <url> <usd> [crypto]   — mark lead as paid + record earnings
    /pipeline [status]           — show pipeline entries (filter by status optional)
    /earnings                    — total earnings stats + by-source breakdown
    /daily                       — today's lead summary
    /sources                     — list active sources
    /addsub <name>               — add a subreddit to scan list
    /remsub <name>               — remove a subreddit
    /settings                    — show current settings
    /set <key> <value>           — change a setting live (min_score, max_age_hours)
    /ping                        — health check

Run locally:
    export TELEGRAM_BOT_TOKEN=...
    python bot.py
"""
from __future__ import annotations
import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
if not TOKEN:
    log.error("TELEGRAM_BOT_TOKEN env var not set.")
    sys.exit(1)

BASE = f"https://api.telegram.org/bot{TOKEN}"
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LEADS_JSON = DATA_DIR / "leads.json"
SETTINGS_JSON = DATA_DIR / "settings.json"
PIPELINE_DB = DATA_DIR / "pipeline.db"

# Import pipeline tracker (lazy)
sys.path.insert(0, str(HERE))
try:
    from leadfinder.pipeline import Pipeline
    PIPE = Pipeline(PIPELINE_DB)
except Exception as e:
    log.warning("pipeline import failed: %s", e)
    PIPE = None

# ---------- Default settings ----------

DEFAULT_SETTINGS = {
    "min_score": 40,
    "max_age_hours": 72,
    "max_messages_per_run": 20,
    "scan_interval_min": 30,
    "active_sources": ["reddit", "hackernews", "bitcointalk", "4chan", "mastodon"],
    "active_niches": ["writing", "dev", "design", "video", "data", "va", "crypto", "translation", "audio", "marketing", "general"],
}


def load_settings() -> dict:
    if SETTINGS_JSON.exists():
        try:
            return {**DEFAULT_SETTINGS, **json.loads(SETTINGS_JSON.read_text())}
        except Exception:
            pass
    return dict(DEFAULT_SETTINGS)


def save_settings(s: dict) -> None:
    SETTINGS_JSON.write_text(json.dumps(s, indent=2), encoding="utf-8")


# ---------- Telegram API helpers ----------

def tg_call(method: str, **params) -> dict:
    url = f"{BASE}/{method}"
    payload = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        log.warning("tg %s -> HTTP %s", method, e.code)
        return {"ok": False}
    except Exception as e:
        log.warning("tg %s -> %s", method, e)
        return {"ok": False}


def send_message(chat_id: int | str, text: str, *, reply_to: int | None = None) -> bool:
    if not text:
        return False
    chunks = [text[i : i + 4000] for i in range(0, len(text), 4000)]
    ok = True
    for chunk in chunks:
        params = {
            "chat_id": str(chat_id),
            "text": chunk,
            "parse_mode": "Markdown",
            "disable_web_page_preview": "true",
        }
        if reply_to:
            params["reply_to_message_id"] = str(reply_to)
        r = tg_call("sendMessage", **params)
        if not r.get("ok"):
            params.pop("parse_mode")
            r = tg_call("sendMessage", **params)
            if not r.get("ok"):
                ok = False
        time.sleep(0.3)
    return ok


def get_updates(offset: int | None = None, timeout: int = 30) -> list:
    params = {"timeout": str(timeout), "allowed_updates": json.dumps(["message"])}
    if offset:
        params["offset"] = str(offset)
    r = tg_call("getUpdates", **params)
    if not r.get("ok"):
        log.warning("getUpdates failed: %s", r)
        time.sleep(5)
        return []
    return r.get("result", [])


# ---------- Commands ----------

def cmd_start(chat_id: int) -> str:
    return (
        "👋 *LeadFinder bot alive (300IQ edition).*\n\n"
        f"Your chat\\_id: `{chat_id}`\n"
        f"Save this for the GitHub Secret `TELEGRAM_CHAT_ID`.\n\n"
        "*Quick start:*\n"
        "• `/scan` — scan now, get top 5 leads\n"
        "• `/leads 10` — show top 10 from last scan\n"
        "• `/stats` — counts by source + niche\n"
        "• `/niche dev` — filter to dev gigs\n"
        "• `/convert <url> contacted` — mark lead as contacted\n"
        "• `/paid <url> 150` — mark paid + track $150 earnings\n"
        "• `/pipeline` — show your lead pipeline\n"
        "• `/earnings` — total earnings + by source\n"
        "• `/settings` — view current scan settings\n"
        "• `/set min_score 50` — raise quality threshold\n\n"
        "*Full command list:* `/help`"
    )


def cmd_help() -> str:
    return (
        "*LeadFinder v2 commands:*\n\n"
        "*Scanning:*\n"
        "• `/scan` — run scan\\_v2.py, send top 5 new leads\n"
        "• `/leads [N]` — top N from last scan (default 10)\n"
        "• `/stats` — counts by source + score band + niche\n"
        "• `/daily` — today's summary\n"
        "• `/sources` — list active sources\n\n"
        "*Filtering:*\n"
        "• `/niche <name>` — filter to niche (writing/dev/design/video/data/va/crypto/translation/audio/marketing)\n\n"
        "*Pipeline:*\n"
        "• `/convert <url> <status> [notes]` — move lead through pipeline\n"
        "  status: new, contacted, replied, quoted, in_progress, paid, rejected, ghosted\n"
        "• `/paid <url> <usd> [crypto]` — record payment\n"
        "• `/pipeline [status]` — show pipeline (filter optional)\n"
        "• `/earnings` — total + by-source earnings\n\n"
        "*Settings:*\n"
        "• `/settings` — show current\n"
        "• `/set <key> <value>` — change (min_score, max_age_hours, max_messages_per_run, scan_interval_min)\n"
        "• `/addsub <name>` — add subreddit\n"
        "• `/remsub <name>` — remove subreddit\n\n"
        "*Other:*\n"
        "• `/ping` — health check"
    )


def cmd_scan(chat_id: int) -> None:
    send_message(chat_id, "🔍 *Scanning all sources...* (~30-120s)")
    start = time.time()
    try:
        result = subprocess.run(
            ["python3", str(HERE / "scan_v2.py")],
            cwd=str(HERE),
            capture_output=True,
            text=True,
            timeout=300,
        )
        log.info("scan exit=%d time=%.1fs", result.returncode, time.time() - start)
        if result.returncode != 0:
            send_message(chat_id, f"⚠️ Scan exited {result.returncode}.\n```\n{result.stderr[-1000:]}\n```")
            return
    except subprocess.TimeoutExpired:
        send_message(chat_id, "⚠️ Scan timed out after 5min.")
        return
    except Exception as e:
        send_message(chat_id, f"⚠️ Scan failed: {e}")
        return

    if not LEADS_JSON.exists():
        send_message(chat_id, "⚠️ No leads.json found.")
        return
    try:
        leads = json.loads(LEADS_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        send_message(chat_id, f"⚠️ Parse failed: {e}")
        return

    if not leads:
        send_message(chat_id, "_No leads matched this scan._")
        return

    # Track new leads in pipeline DB
    new_count = 0
    if PIPE:
        for l in leads:
            if PIPE.upsert_lead(l.get("url",""), l.get("title",""), l.get("source",""), l.get("score",0)):
                new_count += 1

    top = sorted(leads, key=lambda x: -x.get("score", 0))[:3]  # top 3 (Telegram chunk limit)
    elapsed = time.time() - start
    header = f"✅ *Scan done in {elapsed:.0f}s* — {len(leads)} leads ({new_count} new). Top 3 with reply text:"
    send_message(chat_id, header)

    # Send each lead as its own message — title + URL + budget + reply text in code block
    for i, l in enumerate(top, 1):
        title = (l.get("title") or "")[:90]
        url = l.get("url", "")
        source = l.get("source", "")
        score = l.get("score", 0)
        niche = l.get("niche", "general")
        age = l.get("age_hours", 0)
        budget = ", ".join(l.get("budget_signals", [])) or "—"
        snippet = (l.get("snippet") or "")[:300].replace("\n", " ")
        outreach = l.get("outreach_draft") or ""

        msg = (
            f"*{i}. [{score}] {title}*\n"
            f"`{source}` | `{niche}` | {age:.0f}h ago | budget: {budget}\n"
            f"\n"
            f"*Post URL:* {url}\n"
        )
        if snippet:
            msg += f"\n_{snippet}_\n"
        if outreach:
            msg += f"\n*Reply text (copy & paste as Reddit comment/DM):*\n"
            msg += f"```\n{outreach}\n```\n"
        send_message(chat_id, msg)


def cmd_lead(url: str) -> str:
    """Show full lead detail + ready-to-paste reply for a specific URL."""
    if not LEADS_JSON.exists():
        return "_No leads yet._"
    try:
        leads = json.loads(LEADS_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        return f"⚠️ Parse failed: {e}"
    lead = next((l for l in leads if l.get("url") == url), None)
    if not lead:
        return f"Lead not found: {url}\n\nUse `/leads` to see URLs."
    title = lead.get("title") or ""
    source = lead.get("source", "")
    score = lead.get("score", 0)
    niche = lead.get("niche", "general")
    age = lead.get("age_hours", 0)
    budget = ", ".join(lead.get("budget_signals", [])) or "—"
    payment = ", ".join(lead.get("payment_signals", [])) or "—"
    snippet = (lead.get("snippet") or "")[:1000].replace("\n", " ")
    outreach = lead.get("outreach_draft") or ""

    msg = (
        f"*[{score}] {title}*\n"
        f"`{source}` | `{niche}` | {age:.0f}h ago\n"
        f"\n"
        f"*URL:* {url}\n"
        f"*Budget:* {budget}\n"
        f"*Payment:* {payment}\n"
    )
    if snippet:
        msg += f"\n*Post body:*\n{snippet}\n"
    if outreach:
        msg += f"\n*Reply text (copy & paste):*\n```\n{outreach}\n```"
    return msg


def cmd_leads(limit: int = 10, niche: str | None = None) -> str:
    if not LEADS_JSON.exists():
        return "_No leads yet. Run /scan first._"
    try:
        leads = json.loads(LEADS_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        return f"⚠️ Parse failed: {e}"
    if not leads:
        return "_No leads in store._"
    if niche:
        leads = [l for l in leads if l.get("niche") == niche]
        if not leads:
            return f"_No leads in niche `{niche}`._"
    top = sorted(leads, key=lambda x: -x.get("score", 0))[:limit]
    msg = f"*Top {len(top)} leads"
    if niche:
        msg += f" in `{niche}`"
    msg += f" (of {len(leads)} total):*\n\n"
    for i, l in enumerate(top, 1):
        title = (l.get("title") or "")[:65]
        url = l.get("url", "")
        score = l.get("score", 0)
        age = l.get("age_hours", 0)
        niche_l = l.get("niche", "general")
        budget = ", ".join(l.get("budget_signals", [])) or "—"
        msg += f"*{i}. [{score}] {title}*\n"
        msg += f"  `{niche_l}` | age {age}h | {budget}\n"
        msg += f"  {url}\n\n"
    return msg


def cmd_stats() -> str:
    if not LEADS_JSON.exists():
        return "_No leads yet._"
    try:
        leads = json.loads(LEADS_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        return f"⚠️ Parse failed: {e}"
    if not leads:
        return "_No leads in store._"
    by_src: dict[str, int] = {}
    by_niche: dict[str, int] = {}
    by_band = {"90+": 0, "70-89": 0, "50-69": 0, "<50": 0}
    for l in leads:
        s = l.get("source", "?")
        by_src[s] = by_src.get(s, 0) + 1
        n = l.get("niche", "general")
        by_niche[n] = by_niche.get(n, 0) + 1
        sc = l.get("score", 0)
        if sc >= 90: by_band["90+"] += 1
        elif sc >= 70: by_band["70-89"] += 1
        elif sc >= 50: by_band["50-69"] += 1
        else: by_band["<50"] += 1
    msg = f"*Stats — {len(leads)} leads*\n\n*By source:*\n"
    for s in sorted(by_src, key=lambda x: -by_src[x]):
        msg += f"  `{s}`: {by_src[s]}\n"
    msg += "\n*By niche:*\n"
    for n in sorted(by_niche, key=lambda x: -by_niche[x]):
        msg += f"  `{n}`: {by_niche[n]}\n"
    msg += "\n*By score:*\n"
    for band, n in by_band.items():
        msg += f"  `{band}`: {n}\n"
    return msg


def cmd_pipeline(status: str | None = None) -> str:
    if not PIPE:
        return "⚠️ Pipeline tracking not available."
    entries = PIPE.all(status)
    if not entries:
        return f"_No pipeline entries{f' with status `{status}`' if status else ''}._"
    msg = f"*Pipeline — {len(entries)} entries{f' ({status})' if status else ''}:*\n\n"
    for e in entries[:25]:
        title = (e.title or "")[:60]
        url = e.url
        st = e.status
        usd = e.earnings_usd
        msg += f"• [{e.score}] `{st}` "
        if usd:
            msg += f"`${usd}` "
        msg += f"{title}\n  {url}\n"
    return msg


def cmd_earnings() -> str:
    if not PIPE:
        return "⚠️ Pipeline tracking not available."
    stats = PIPE.stats()
    total_usd = stats.get("total_earnings_usd", 0)
    n_paid = stats.get("n_paid", 0)
    msg = f"*Earnings summary*\n\n"
    msg += f"Total: *${total_usd:.2f}* from {n_paid} paid gig(s)\n\n"
    msg += "*Pipeline:*\n"
    for st in ["new", "contacted", "replied", "quoted", "in_progress", "paid", "rejected", "ghosted"]:
        n = stats.get(st, 0)
        if n:
            msg += f"  `{st}`: {n}\n"
    msg += "\n*By source (paid gigs):*\n"
    for row in stats.get("by_source", []):
        if row["usd"] > 0 or row["n"] > 0:
            msg += f"  `{row['source']}`: {row['n']} lead(s), ${row['usd']:.0f} earned\n"
    return msg


def cmd_convert(args: list[str]) -> str:
    if not PIPE or len(args) < 2:
        return "Usage: `/convert <url> <status> [notes]`\nstatus: new, contacted, replied, quoted, in_progress, paid, rejected, ghosted"
    url = args[0]
    status = args[1].lower()
    notes = " ".join(args[2:]) if len(args) > 2 else ""
    if not PIPE.set_status(url, status, notes=notes):
        return f"⚠️ Lead not found in pipeline: {url}\nRun /scan first."
    return f"✅ Marked as `{status}`:\n{url}"


def cmd_paid(args: list[str]) -> str:
    if not PIPE or len(args) < 2:
        return "Usage: `/paid <url> <usd_amount> [crypto_amount]`"
    url = args[0]
    try:
        usd = float(args[1])
    except ValueError:
        return "USD amount must be a number."
    crypto = " ".join(args[2:]) if len(args) > 2 else ""
    if not PIPE.record_payment(url, usd, crypto):
        return f"⚠️ Lead not found in pipeline: {url}\nRun /scan first."
    return f"💰 Recorded payment: *${usd:.2f}*{f' + {crypto}' if crypto else ''}\n{url}"


def cmd_settings() -> str:
    s = load_settings()
    msg = "*Current settings:*\n\n"
    for k, v in s.items():
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v)
        msg += f"• `{k}`: {v}\n"
    msg += "\nChange with `/set <key> <value>`"
    return msg


def cmd_set(args: list[str]) -> str:
    if len(args) < 2:
        return "Usage: `/set <key> <value>`\nKeys: min_score, max_age_hours, max_messages_per_run, scan_interval_min"
    key = args[0]
    val_str = " ".join(args[1:])
    s = load_settings()
    if key in ("min_score", "max_age_hours", "max_messages_per_run", "scan_interval_min"):
        try:
            s[key] = int(val_str)
            save_settings(s)
            return f"✅ `{key}` = {s[key]}"
        except ValueError:
            return f"`{key}` must be an integer."
    return f"⚠️ Unknown setting `{key}`. Editable: min_score, max_age_hours, max_messages_per_run, scan_interval_min"


def cmd_sources() -> str:
    s = load_settings()
    msg = "*Active sources:*\n\n"
    msg += "• Reddit RSS: " + ", ".join(f"r/{x}" for x in s.get("active_sources", []) if x in ["reddit"]) + "\n"
    msg += "• Hacker News, Bitcointalk, 4chan, Mastodon — all on\n\n"
    msg += "Toggle with `/addsub <name>` or `/remsub <name>` (Reddit only).\n"
    msg += "Default subs are baked into scan_v2.py's REDDIT_SUBS list."
    return msg


def cmd_daily() -> str:
    if not LEADS_JSON.exists():
        return "_No leads yet._"
    try:
        leads = json.loads(LEADS_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        return f"⚠️ Parse failed: {e}"
    today_leads = [l for l in leads if l.get("age_hours", 9999) <= 24]
    if not today_leads:
        return f"_No leads under 24h old. (Total tracked: {len(leads)})_"
    top = sorted(today_leads, key=lambda x: -x.get("score", 0))[:5]
    msg = f"*Daily summary — {len(today_leads)} leads under 24h old (of {len(leads)} total)*\n\n"
    for i, l in enumerate(top, 1):
        title = (l.get("title") or "")[:65]
        url = l.get("url", "")
        score = l.get("score", 0)
        niche = l.get("niche", "general")
        age = l.get("age_hours", 0)
        msg += f"*{i}. [{score}] {title}*\n  `{niche}` | {age:.1f}h ago\n  {url}\n\n"
    return msg


def cmd_ping() -> str:
    return "🏓 pong"


# ---------- Main loop ----------

def handle_update(update: dict) -> None:
    msg = update.get("message") or {}
    text = (msg.get("text") or "").strip()
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    if not chat_id or not text:
        return
    log.info("from=%s chat=%s text=%s", msg.get("from", {}).get("username"), chat_id, text[:80])

    parts = text.split()
    cmd = parts[0].split("@", 1)[0].lower()
    args = parts[1:]

    if cmd == "/start":
        send_message(chat_id, cmd_start(chat_id))
    elif cmd == "/help":
        send_message(chat_id, cmd_help())
    elif cmd == "/scan":
        cmd_scan(chat_id)
    elif cmd == "/leads":
        niche = None
        limit = 10
        for a in args:
            if a.isdigit():
                limit = int(a)
            else:
                niche = a
        send_message(chat_id, cmd_leads(limit, niche))
    elif cmd == "/niche":
        if not args:
            return send_message(chat_id, "Usage: `/niche <name>`\nNiches: writing, dev, design, video, data, va, crypto, translation, audio, marketing")
        send_message(chat_id, cmd_leads(10, args[0]))
    elif cmd == "/stats":
        send_message(chat_id, cmd_stats())
    elif cmd == "/pipeline":
        status = args[0] if args else None
        send_message(chat_id, cmd_pipeline(status))
    elif cmd == "/earnings":
        send_message(chat_id, cmd_earnings())
    elif cmd == "/convert":
        send_message(chat_id, cmd_convert(args))
    elif cmd == "/paid":
        send_message(chat_id, cmd_paid(args))
    elif cmd == "/settings":
        send_message(chat_id, cmd_settings())
    elif cmd == "/set":
        send_message(chat_id, cmd_set(args))
    elif cmd == "/sources":
        send_message(chat_id, cmd_sources())
    elif cmd == "/daily":
        send_message(chat_id, cmd_daily())
    elif cmd == "/lead":
        if not args:
            send_message(chat_id, "Usage: `/lead <url>` — get full lead + reply text")
        else:
            send_message(chat_id, cmd_lead(args[0]))
    elif cmd == "/ping":
        send_message(chat_id, cmd_ping())
    else:
        pass  # ignore unknown


def main():
    log.info("bot starting — 300IQ edition")
    offset = None
    while True:
        try:
            updates = get_updates(offset, timeout=30)
            for update in updates:
                offset = update["update_id"] + 1
                try:
                    handle_update(update)
                except Exception as e:
                    log.exception("handler failed: %s", e)
        except KeyboardInterrupt:
            log.info("shutting down")
            break
        except Exception as e:
            log.exception("poll loop error: %s", e)
            time.sleep(5)


if __name__ == "__main__":
    main()
