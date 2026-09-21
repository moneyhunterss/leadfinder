"""Telegram notifier — sends NEW leads with inline keyboards + outreach draft."""
from __future__ import annotations
import json
import logging
import time
import urllib.parse
import urllib.request
from typing import List
from config import Config
from db import DB

log = logging.getLogger("leadfinder.notifier")


def escape_html(text) -> str:
    if not text: return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _send(token: str, chat_id: str, text: str, reply_markup: dict = None) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "false"}
    if reply_markup: params["reply_markup"] = json.dumps(reply_markup)
    payload = urllib.parse.urlencode(params).encode()
    try:
        req = urllib.request.Request(url, data=payload, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
        if not resp.get("ok"):
            params.pop("parse_mode", None)
            params.pop("reply_markup", None)
            payload = urllib.parse.urlencode(params).encode()
            req = urllib.request.Request(url, data=payload, method="POST")
            with urllib.request.urlopen(req, timeout=15) as r:
                resp = json.loads(r.read())
        return resp.get("ok", False)
    except Exception as e:
        log.warning("Telegram send failed: %s", e)
        return False


def _lead_keyboard(url: str) -> dict:
    import base64
    url_b64 = base64.urlsafe_b64encode(url.encode()).decode()[:56]
    return {"inline_keyboard": [[
        {"text": "🔗 Open", "url": url},
        {"text": "✅ Contacted", "callback_data": f"ct_{url_b64}"},
        {"text": "💰 Paid", "callback_data": f"pd_{url_b64}"},
        {"text": "❌ Reject", "callback_data": f"rj_{url_b64}"},
    ]]}


def _format(lead: dict) -> str:
    title = escape_html((lead.get("title") or "")[:120])
    url = lead.get("url", "")
    source = escape_html(lead.get("source", ""))
    score = lead.get("score", 0)
    niche = escape_html(lead.get("niche", "general"))
    tier = escape_html(lead.get("tier", "unspecified"))
    budget = escape_html(", ".join(lead.get("budget_signals", [])) or "—")
    snippet = escape_html((lead.get("snippet") or "")[:200].replace("\n", " "))
    outreach = escape_html(lead.get("outreach_draft") or "")
    age = lead.get("age_hours", 0)
    return (
        f"<b>[{score}] {title}</b>\n"
        f"<code>{source}</code> | {niche} | {tier} | budget: {budget} | {age}h old\n\n"
        f"<b>URL:</b> {url}\n"
        + (f"\n<i>{snippet}</i>\n" if snippet else "")
        + (f"\n<b>Reply text (copy & paste):</b>\n<pre>{outreach}</pre>" if outreach else "")
    )


def send_new_leads(cfg: Config, db: DB) -> int:
    token = cfg.telegram_token
    chat_id = cfg.telegram_chat_id
    if not token or not chat_id:
        log.error("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
        return 0
    min_score = cfg.notifier.get("min_score", 25)
    max_msgs = cfg.notifier.get("max_messages", 15)
    new = db.get_new_leads(min_score=min_score)
    log.info("new leads above %d: %d", min_score, len(new))
    if not new:
        log.info("no new leads, staying silent")
        return 0
    sent = 0
    for lead in new[:max_msgs]:
        msg = _format(lead)
        kb = _lead_keyboard(lead.get("url", ""))
        if _send(token, chat_id, msg, kb): sent += 1
        time.sleep(1)
    db.mark_notified()
    log.info("sent %d/%d leads", sent, len(new[:max_msgs]))
    return sent
