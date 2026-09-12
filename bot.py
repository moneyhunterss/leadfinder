#!/usr/bin/env python3
"""LeadFinder Telegram bot — HTML parse mode, safe brackets, clean formatting.

Commands:
    /start            — register, show chat_id
    /help             — list all commands
    /scan             — run fresh scan, send top 3 leads with reply text in code block
    /leads [N]        — top N leads from last scan (default 10)
    /lead <url>       — full lead detail + reply text
    /niche <name>     — filter leads by niche
    /stats            — counts by source + niche + score band
    /pipeline [status] — show pipeline entries
    /earnings         — total + by-source earnings
    /convert <url> <status> [notes]  — move lead through pipeline
    /paid <url> <usd> [crypto]   — record payment
    /daily            — today's lead summary
    /sources          — list active sources
    /settings         — show current settings
    /set <key> <val>  — change min_score, max_age_hours, etc. live
    /ping             — health check
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

sys.path.insert(0, str(HERE))
try:
    from leadfinder.pipeline import Pipeline
    PIPE = Pipeline(PIPELINE_DB)
except Exception as e:
    log.warning("pipeline import failed: %s", e)
    PIPE = None

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


# ---------- Telegram API ----------

def escape_html(text) -> str:
    if text is None:
        return ""
    return (str(text).replace("&", "&amp;")
                     .replace("<", "&lt;")
                     .replace(">", "&gt;"))


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


def send_message(chat_id, text: str, *, reply_to: int | None = None) -> bool:
    if not text:
        return False
    chunks = [text[i : i + 4000] for i in range(0, len(text), 4000)]
    ok = True
    for chunk in chunks:
        params = {
            "chat_id": str(chat_id),
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": "false",
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


# ---------- Lead formatters ----------

def fmt_lead_card(i: int | None, l: dict) -> str:
    """HTML-formatted lead card with URL + reply text in code block."""
    title = escape_html((l.get("title") or "")[:90])
    url = l.get("url", "")
    source = escape_html(l.get("source", ""))
    score = l.get("score", 0)
    niche = escape_html(l.get("niche", "general"))
    age = l.get("age_hours", 0)
    budget = escape_html(", ".join(l.get("budget_signals", [])) or "—")
    snippet = escape_html((l.get("snippet") or "")[:300].replace("\n", " "))
    outreach = escape_html(l.get("outreach_draft") or "")

    prefix = f"<b>{i}. [{score}] {title}</b>\n" if i else f"<b>[{score}] {title}</b>\n"
    msg = (
        f"{prefix}"
        f"<code>{source}</code> | <code>{niche}</code> | {age:.0f}h ago | budget: {budget}\n\n"
        f"<b>Post URL:</b> {url}\n"
    )
    if snippet:
        msg += f"\n<i>{snippet}</i>\n"
    if outreach:
        msg += f"\n<b>Reply text (copy & paste):</b>\n<pre>{outreach}</pre>\n"
    return msg


# ---------- Commands ----------

def cmd_start(chat_id: int) -> str:
    return (
        "👋 <b>LeadFinder bot alive (300IQ edition).</b>\n\n"
        f"Your chat_id: <code>{chat_id}</code>\n"
        f"Save this for the GitHub Secret <code>TELEGRAM_CHAT_ID</code>.\n\n"
        "<b>Quick start:</b>\n"
        "• <code>/scan</code> — scan now, get top 3 leads with reply text\n"
        "• <code>/leads 10</code> — show top 10 from last scan\n"
        "• <code>/lead &lt;url&gt;</code> — full lead detail + reply text\n"
        "• <code>/niche dev</code> — filter to dev gigs\n"
        "• <code>/convert &lt;url&gt; contacted</code> — mark lead as contacted\n"
        "• <code>/paid &lt;url&gt; 150</code> — mark paid + track $150 earnings\n"
        "• <code>/pipeline</code> — show your lead pipeline\n"
        "• <code>/earnings</code> — total + by-source earnings\n"
        "• <code>/settings</code> / <code>/set min_score 50</code>\n\n"
        "<b>Full list:</b> <code>/help</code>"
    )


def cmd_help() -> str:
    return (
        "<b>LeadFinder v2 commands:</b>\n\n"
        "<b>Scanning:</b>\n"
        "• <code>/scan</code> — fresh scan, top 3 leads with reply text inline\n"
        "• <code>/leads [N]</code> — top N from last scan (default 10)\n"
        "• <code>/lead &lt;url&gt;</code> — full detail + reply text\n"
        "• <code>/stats</code> — counts by source + score + niche\n"
        "• <code>/daily</code> — today's summary\n"
        "• <code>/sources</code> — list active sources\n\n"
        "<b>Filtering:</b>\n"
        "• <code>/niche &lt;name&gt;</code> — writing/dev/design/video/data/va/crypto/translation/audio/marketing\n\n"
        "<b>Pipeline:</b>\n"
        "• <code>/convert &lt;url&gt; &lt;status&gt; [notes]</code>\n"
        "  status: new/contacted/replied/quoted/in_progress/paid/rejected/ghosted\n"
        "• <code>/paid &lt;url&gt; &lt;usd&gt; [crypto]</code>\n"
        "• <code>/pipeline [status]</code> — show pipeline\n"
        "• <code>/earnings</code> — total + by-source\n\n"
        "<b>Settings:</b>\n"
        "• <code>/settings</code> — show current\n"
        "• <code>/set &lt;key&gt; &lt;value&gt;</code> — min_score / max_age_hours / etc.\n\n"
        "<b>Other:</b> <code>/ping</code>"
    )


def cmd_scan(chat_id: int) -> None:
    send_message(chat_id, "🔍 <b>Scanning all sources...</b> (~30-120s)")
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
            send_message(chat_id, f"⚠️ Scan exited {result.returncode}.\n<pre>{escape_html(result.stderr[-1000:])}</pre>")
            return
    except subprocess.TimeoutExpired:
        send_message(chat_id, "⚠️ Scan timed out after 5min.")
        return
    except Exception as e:
        send_message(chat_id, f"⚠️ Scan failed: {escape_html(str(e))}")
        return

    if not LEADS_JSON.exists():
        send_message(chat_id, "⚠️ No leads.json found.")
        return
    try:
        leads = json.loads(LEADS_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        send_message(chat_id, f"⚠️ Parse failed: {escape_html(str(e))}")
        return

    if not leads:
        send_message(chat_id, "<i>No leads matched this scan.</i>")
        return

    new_count = 0
    if PIPE:
        for l in leads:
            if PIPE.upsert_lead(l.get("url",""), l.get("title",""), l.get("source",""), l.get("score",0)):
                new_count += 1

    top = sorted(leads, key=lambda x: -x.get("score", 0))[:3]
    elapsed = time.time() - start
    send_message(chat_id, f"✅ <b>Scan done in {elapsed:.0f}s</b> — {len(leads)} leads ({new_count} new). Top 3 with reply text:")
    for i, l in enumerate(top, 1):
        send_message(chat_id, fmt_lead_card(i, l))


def cmd_lead(url: str) -> str:
    if not LEADS_JSON.exists():
        return "<i>No leads yet.</i>"
    try:
        leads = json.loads(LEADS_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        return f"⚠️ Parse failed: {escape_html(str(e))}"
    lead = next((l for l in leads if l.get("url") == url), None)
    if not lead:
        return f"Lead not found: {escape_html(url)}\n\nUse <code>/leads</code> to see URLs."
    return fmt_lead_card(None, lead)


def cmd_leads(limit: int = 10, niche: str | None = None) -> str:
    if not LEADS_JSON.exists():
        return "<i>No leads yet. Run /scan first.</i>"
    try:
        leads = json.loads(LEADS_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        return f"⚠️ Parse failed: {escape_html(str(e))}"
    if not leads:
        return "<i>No leads in store.</i>"
    if niche:
        leads = [l for l in leads if l.get("niche") == niche]
        if not leads:
            return f"<i>No leads in niche <code>{escape_html(niche)}</code>.</i>"
    top = sorted(leads, key=lambda x: -x.get("score", 0))[:limit]
    header = f"<b>Top {len(top)} leads"
    if niche:
        header += f" in <code>{escape_html(niche)}</code>"
    header += f" (of {len(leads)} total):</b>\n\n"
    parts = [header]
    for i, l in enumerate(top, 1):
        title = escape_html((l.get("title") or "")[:65])
        url = l.get("url", "")
        score = l.get("score", 0)
        age = l.get("age_hours", 0)
        niche_l = escape_html(l.get("niche", "general"))
        budget = escape_html(", ".join(l.get("budget_signals", [])) or "—")
        parts.append(
            f"<b>{i}. [{score}] {title}</b>\n"
            f"  <code>{niche_l}</code> | age {age:.0f}h | {budget}\n"
            f"  {url}\n\n"
        )
    return "".join(parts)


def cmd_stats() -> str:
    if not LEADS_JSON.exists():
        return "<i>No leads yet.</i>"
    try:
        leads = json.loads(LEADS_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        return f"⚠️ Parse failed: {escape_html(str(e))}"
    if not leads:
        return "<i>No leads in store.</i>"
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
    msg = f"<b>Stats — {len(leads)} leads</b>\n\n<b>By source:</b>\n"
    for s in sorted(by_src, key=lambda x: -by_src[x]):
        msg += f"  <code>{escape_html(s)}</code>: {by_src[s]}\n"
    msg += "\n<b>By niche:</b>\n"
    for n in sorted(by_niche, key=lambda x: -by_niche[x]):
        msg += f"  <code>{escape_html(n)}</code>: {by_niche[n]}\n"
    msg += "\n<b>By score:</b>\n"
    for band, n in by_band.items():
        msg += f"  <code>{escape_html(band)}</code>: {n}\n"
    return msg


def cmd_pipeline(status: str | None = None) -> str:
    if not PIPE:
        return "⚠️ Pipeline tracking not available."
    entries = PIPE.all(status)
    if not entries:
        return f"<i>No pipeline entries{f' with status <code>{escape_html(status)}</code>' if status else ''}.</i>"
    msg = f"<b>Pipeline — {len(entries)} entries{f' ({escape_html(status)})' if status else ''}:</b>\n\n"
    for e in entries[:25]:
        title = escape_html((e.title or "")[:60])
        url = e.url
        st = escape_html(e.status)
        usd = e.earnings_usd
        msg += f"• [{e.score}] <code>{st}</code> "
        if usd:
            msg += f"<b>${usd:.0f}</b> "
        msg += f"{title}\n  {url}\n"
    return msg


def cmd_earnings() -> str:
    if not PIPE:
        return "⚠️ Pipeline tracking not available."
    stats = PIPE.stats()
    total_usd = stats.get("total_earnings_usd", 0)
    n_paid = stats.get("n_paid", 0)
    msg = f"<b>Earnings summary</b>\n\n"
    msg += f"Total: <b>${total_usd:.2f}</b> from {n_paid} paid gig(s)\n\n"
    msg += "<b>Pipeline:</b>\n"
    for st in ["new", "contacted", "replied", "quoted", "in_progress", "paid", "rejected", "ghosted"]:
        n = stats.get(st, 0)
        if n:
            msg += f"  <code>{st}</code>: {n}\n"
    msg += "\n<b>By source (paid gigs):</b>\n"
    for row in stats.get("by_source", []):
        if row["usd"] > 0 or row["n"] > 0:
            msg += f"  <code>{escape_html(row['source'])}</code>: {row['n']} lead(s), ${row['usd']:.0f} earned\n"
    return msg


def cmd_convert(args: list[str]) -> str:
    if not PIPE or len(args) < 2:
        return ("Usage: <code>/convert &lt;url&gt; &lt;status&gt; [notes]</code>\n"
                "status: new, contacted, replied, quoted, in_progress, paid, rejected, ghosted")
    url = args[0]
    status = args[1].lower()
    notes = " ".join(args[2:]) if len(args) > 2 else ""
    if not PIPE.set_status(url, status, notes=notes):
        return f"⚠️ Lead not found in pipeline: {escape_html(url)}\nRun /scan first."
    return f"✅ Marked as <code>{escape_html(status)}</code>:\n{url}"


def cmd_paid(args: list[str]) -> str:
    if not PIPE or len(args) < 2:
        return "Usage: <code>/paid &lt;url&gt; &lt;usd_amount&gt; [crypto_amount]</code>"
    url = args[0]
    try:
        usd = float(args[1])
    except ValueError:
        return "USD amount must be a number."
    crypto = " ".join(args[2:]) if len(args) > 2 else ""
    if not PIPE.record_payment(url, usd, crypto):
        return f"⚠️ Lead not found in pipeline: {escape_html(url)}\nRun /scan first."
    return f"💰 Recorded payment: <b>${usd:.2f}</b>{f' + {escape_html(crypto)}' if crypto else ''}\n{url}"


def cmd_settings() -> str:
    s = load_settings()
    msg = "<b>Current settings:</b>\n\n"
    for k, v in s.items():
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v)
        msg += f"• <code>{escape_html(k)}</code>: {escape_html(v)}\n"
    msg += "\nChange with <code>/set &lt;key&gt; &lt;value&gt;</code>"
    return msg


def cmd_set(args: list[str]) -> str:
    if len(args) < 2:
        return ("Usage: <code>/set &lt;key&gt; &lt;value&gt;</code>\n"
                "Keys: min_score, max_age_hours, max_messages_per_run, scan_interval_min")
    key = args[0]
    val_str = " ".join(args[1:])
    s = load_settings()
    if key in ("min_score", "max_age_hours", "max_messages_per_run", "scan_interval_min"):
        try:
            s[key] = int(val_str)
            save_settings(s)
            return f"✅ <code>{escape_html(key)}</code> = {s[key]}"
        except ValueError:
            return f"<code>{escape_html(key)}</code> must be an integer."
    return (f"⚠️ Unknown setting <code>{escape_html(key)}</code>. "
            f"Editable: min_score, max_age_hours, max_messages_per_run, scan_interval_min")


def cmd_sources() -> str:
    s = load_settings()
    msg = "<b>Active sources:</b>\n\n"
    msg += "• Reddit RSS: 32 subs (r/forhire, r/Jobs4Bitcoins, r/DesignJobs, r/remotejobs, r/HireaWriter, etc.)\n"
    msg += "• Hacker News Algolia\n"
    msg += "• Bitcointalk board 73\n"
    msg += "• 4chan /g/ + /biz/ + /wsr/\n"
    msg += "• Mastodon (optional)\n\n"
    msg += "Default subs are baked into scan_v2.py's REDDIT_SUBS list."
    return msg


def cmd_daily() -> str:
    if not LEADS_JSON.exists():
        return "<i>No leads yet.</i>"
    try:
        leads = json.loads(LEADS_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        return f"⚠️ Parse failed: {escape_html(str(e))}"
    today_leads = [l for l in leads if l.get("age_hours", 9999) <= 24]
    if not today_leads:
        return f"<i>No leads under 24h old. (Total tracked: {len(leads)})</i>"
    top = sorted(today_leads, key=lambda x: -x.get("score", 0))[:5]
    msg = f"<b>Daily summary — {len(today_leads)} leads under 24h old (of {len(leads)} total)</b>\n\n"
    for i, l in enumerate(top, 1):
        title = escape_html((l.get("title") or "")[:65])
        url = l.get("url", "")
        score = l.get("score", 0)
        niche = escape_html(l.get("niche", "general"))
        age = l.get("age_hours", 0)
        msg += f"<b>{i}. [{score}] {title}</b>\n  <code>{niche}</code> | {age:.1f}h ago\n  {url}\n\n"
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
            send_message(chat_id, "Usage: <code>/niche &lt;name&gt;</code>\nNiches: writing, dev, design, video, data, va, crypto, translation, audio, marketing")
        else:
            send_message(chat_id, cmd_leads(10, args[0]))
    elif cmd == "/lead":
        if not args:
            send_message(chat_id, "Usage: <code>/lead &lt;url&gt;</code> — get full lead + reply text")
        else:
            send_message(chat_id, cmd_lead(args[0]))
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
    elif cmd == "/ping":
        send_message(chat_id, cmd_ping())
    else:
        pass


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
