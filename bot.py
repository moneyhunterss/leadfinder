#!/usr/bin/env python3
"""LeadFinder v3.5 — Telegram bot with inline keyboards + pipeline tracking."""
from __future__ import annotations
import base64
import json
import logging
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from config import Config
from db import DB
from notifiers.telegram import escape_html, _send

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")
cfg = Config()
db = DB()
TOKEN = cfg.telegram_token
CHAT_ID = cfg.telegram_chat_id
BASE = f"https://api.telegram.org/bot{TOKEN}"
HERE = Path(__file__).resolve().parent


def tg(method, **params):
    url = f"{BASE}/{method}"
    payload = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=payload, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r: return json.loads(r.read())
    except Exception as e:
        log.warning("tg %s -> %s", method, e)
        return {"ok": False}


def send(chat_id, text, reply_markup=None):
    params = {"chat_id": str(chat_id), "text": text, "parse_mode": "HTML", "disable_web_page_preview": "false"}
    if reply_markup: params["reply_markup"] = json.dumps(reply_markup)
    r = tg("sendMessage", **params)
    if not r.get("ok"):
        params.pop("parse_mode", None)
        params.pop("reply_markup", None)
        r = tg("sendMessage", **params)
    return r.get("ok", False)


def main_menu():
    return {"inline_keyboard": [
        [{"text": "🔍 Scan", "callback_data": "scan"}, {"text": "📋 Top 10", "callback_data": "leads"}],
        [{"text": "📊 Stats", "callback_data": "stats"}, {"text": "🏆 Pipeline", "callback_data": "pipe"}],
        [{"text": "💰 Earnings", "callback_data": "earn"}, {"text": "💎 Elite", "callback_data": "tier_elite"}],
        [{"text": "⚡ Micro", "callback_data": "tier_micro"}, {"text": "❓ Help", "callback_data": "help"}],
    ]}


def cmd_scan(chat_id):
    send(chat_id, "🔍 Scanning... (~60s)")
    try:
        proc = subprocess.Popen(["python3", "-u", str(HERE / "scan.py")], cwd=str(HERE),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        proc.communicate(timeout=540)
    except Exception as e:
        send(chat_id, f"⚠️ {escape_html(str(e))}")
        return
    leads = db.load_leads()
    if not leads: send(chat_id, "<i>No leads found.</i>"); return
    top = sorted(leads, key=lambda x: -x.get("score", 0))[:3]
    send(chat_id, f"✅ <b>{len(leads)} leads</b>. Top 3:")
    for i, l in enumerate(top, 1):
        send(chat_id, f"<b>{i}. [{l.get('score',0)}] {escape_html(l.get('title','')[:80])}</b>\n"
                      f"<code>{escape_html(l.get('source',''))}</code> | {escape_html(l.get('niche',''))} | {escape_html(l.get('tier',''))}\n"
                      f"URL: {l.get('url','')}\n\n"
                      f"<pre>{escape_html(l.get('outreach_draft','')[:500])}</pre>")


def cmd_leads(chat_id, limit=10):
    leads = db.load_leads()
    if not leads: send(chat_id, "<i>No leads yet.</i>"); return
    top = sorted(leads, key=lambda x: -x.get("score", 0))[:limit]
    msg = f"<b>Top {len(top)} leads:</b>\n\n"
    for i, l in enumerate(top, 1):
        msg += f"<b>{i}. [{l.get('score',0)}] {escape_html(l.get('title','')[:55])}</b>\n  {l.get('url','')}\n\n"
    send(chat_id, msg)


def cmd_stats(chat_id):
    leads = db.load_leads()
    by_s, by_t, by_n = {}, {}, {}
    for l in leads:
        by_s[l.get("source","?")] = by_s.get(l.get("source","?"),0)+1
        by_t[l.get("tier","?")] = by_t.get(l.get("tier","?"),0)+1
        by_n[l.get("niche","?")] = by_n.get(l.get("niche","?"),0)+1
    msg = f"<b>{len(leads)} leads</b>\n\n<b>By source:</b>\n"
    for s,n in sorted(by_s.items(), key=lambda x:-x[1])[:8]: msg += f"  <code>{escape_html(s)}</code>: {n}\n"
    msg += "\n<b>By tier:</b>\n"
    for t in ["elite","pro","standard","micro","unspecified"]:
        if by_t.get(t): msg += f"  <code>{t}</code>: {by_t[t]}\n"
    send(chat_id, msg)


def cmd_pipe(chat_id):
    s = db.pipe_stats()
    msg = f"<b>Pipeline — {s['total']} leads</b>\n\n"
    for st,n in s.get("by_status",{}).items(): msg += f"  <code>{st}</code>: {n}\n"
    if s.get("total_earnings"): msg += f"\n💰 Total: ${s['total_earnings']:.0f}"
    send(chat_id, msg)


def cmd_earn(chat_id):
    s = db.pipe_stats()
    msg = f"<b>Earnings</b>\n\nTotal: ${s.get('total_earnings',0):.2f}\n\n"
    for st,n in s.get("by_status",{}).items(): msg += f"  <code>{st}</code>: {n}\n"
    send(chat_id, msg)


def cmd_tier(chat_id, tier):
    leads = db.load_leads()
    filtered = [l for l in leads if l.get("tier") == tier]
    if not filtered: send(chat_id, f"<i>No {tier} leads.</i>"); return
    top = sorted(filtered, key=lambda x: -x.get("score",0))[:10]
    msg = f"<b>{tier.upper()} — {len(filtered)} leads</b>\n\n"
    for i, l in enumerate(top, 1):
        msg += f"<b>{i}. [{l.get('score',0)}] {escape_html(l.get('title','')[:55])}</b>\n  {l.get('url','')}\n\n"
    send(chat_id, msg)


def handle_callback(query):
    chat_id = query["message"]["chat"]["id"]
    data = query.get("data", "")
    tg("answerCallbackQuery", callback_query_id=query["id"])
    if data == "scan": cmd_scan(chat_id)
    elif data == "leads": cmd_leads(chat_id)
    elif data == "stats": cmd_stats(chat_id)
    elif data == "pipe": cmd_pipe(chat_id)
    elif data == "earn": cmd_earn(chat_id)
    elif data == "help": send(chat_id, "Tap buttons 👇", reply_markup=main_menu())
    elif data.startswith("tier_"): cmd_tier(chat_id, data[5:])
    elif data.startswith("ct_") or data.startswith("pd_") or data.startswith("rj_"):
        # Pipeline status update from inline keyboard
        try:
            url_b64 = data[3:] + "==="
            url = base64.urlsafe_b64decode(url_b64).decode()
            status = {"ct": "contacted", "pd": "paid", "rj": "rejected"}[data[:2]]
            db.set_status(url, status)
            send(chat_id, f"✅ Marked as <code>{status}</code>")
        except: send(chat_id, "⚠️ Could not update.")


def handle_message(msg):
    text = (msg.get("text") or "").strip()
    chat_id = msg.get("chat",{}).get("id")
    if not chat_id or not text: return
    cmd = text.split()[0].lower().split("@")[0]
    args = text.split()[1:]
    if cmd == "/start": send(chat_id, "👋 <b>LeadFinder v3.5</b> 👇", reply_markup=main_menu())
    elif cmd == "/scan": cmd_scan(chat_id)
    elif cmd == "/leads": cmd_leads(chat_id, int(args[0]) if args and args[0].isdigit() else 10)
    elif cmd == "/stats": cmd_stats(chat_id)
    elif cmd == "/pipeline": cmd_pipe(chat_id)
    elif cmd == "/earnings": cmd_earn(chat_id)
    elif cmd == "/tier" and args: cmd_tier(chat_id, args[0])
    elif cmd == "/ping": send(chat_id, "🏓 pong")
    elif cmd == "/menu": send(chat_id, "👇", reply_markup=main_menu())


def main():
    log.info("bot v3.5 starting")
    if CHAT_ID: send(CHAT_ID, "🟢 <b>Bot v3.5 started</b> 👇", reply_markup=main_menu())
    offset = None
    last_hb = time.time()
    while True:
        try:
            params = {"timeout": "30", "allowed_updates": json.dumps(["message", "callback_query"])}
            if offset: params["offset"] = str(offset)
            r = tg("getUpdates", **params)
            if not r.get("ok"): time.sleep(5); continue
            for update in r.get("result", []):
                offset = update["update_id"] + 1
                if "callback_query" in update: handle_callback(update["callback_query"])
                elif "message" in update: handle_message(update["message"])
            if time.time() - last_hb > 1800:
                last_hb = time.time()
                if CHAT_ID: send(CHAT_ID, f"🟢 <b>Alive</b> — {time.strftime('%H:%M UTC', time.gmtime())}")
        except KeyboardInterrupt: break
        except Exception as e:
            log.exception("poll error: %s", e)
            time.sleep(5)


if __name__ == "__main__":
    main()
