"""Database — JSON file state (works everywhere, zero deps).
Swap to Turso/libSQL by setting turso.url + turso.auth_token in config.
"""
from __future__ import annotations
import json
import os
import time
from pathlib import Path
from typing import List, Optional


DATA_DIR = Path(os.environ.get("LEADFINDER_DATA", "data"))


class DB:
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.leads_file = DATA_DIR / "leads.json"
        self.prev_file = DATA_DIR / "leads_prev.json"
        self.pipe_file = DATA_DIR / "pipeline.json"

    def load_leads(self) -> list[dict]:
        if self.leads_file.exists():
            try: return json.loads(self.leads_file.read_text())
            except: return []
        return []

    def save_leads(self, leads: list[dict]):
        self.leads_file.write_text(json.dumps(leads, indent=2, ensure_ascii=False))

    def load_prev(self) -> list[dict]:
        if self.prev_file.exists():
            try: return json.loads(self.prev_file.read_text())
            except: return []
        return []

    def save_prev(self):
        self.prev_file.write_text(json.dumps(self.load_leads(), ensure_ascii=False))

    def get_new_leads(self, min_score: int = 0) -> list[dict]:
        curr = self.load_leads()
        prev_urls = {l.get("url") for l in self.load_prev()}
        new = [l for l in curr if l.get("url") not in prev_urls and l.get("score", 0) >= min_score]
        return sorted(new, key=lambda x: -x.get("score", 0))

    def mark_notified(self):
        self.save_prev()

    # ─── Pipeline ───
    def load_pipe(self) -> dict:
        if self.pipe_file.exists():
            try: return json.loads(self.pipe_file.read_text())
            except: return {}
        return {}

    def save_pipe(self, d: dict):
        self.pipe_file.write_text(json.dumps(d, indent=2, ensure_ascii=False))

    def upsert_pipe(self, url: str, title: str, source: str, score: int = 0) -> bool:
        p = self.load_pipe()
        if url in p:
            p[url]["score"] = score; p[url]["title"] = title
            self.save_pipe(p); return False
        p[url] = {"title": title, "source": source, "score": score, "status": "new",
                  "earnings_usd": 0, "earnings_crypto": "", "first_seen": time.time(),
                  "last_touched": time.time(), "notes": ""}
        self.save_pipe(p); return True

    def set_status(self, url: str, status: str, notes: str = "") -> bool:
        p = self.load_pipe()
        if url not in p: return False
        p[url]["status"] = status; p[url]["last_touched"] = time.time()
        if notes: p[url]["notes"] = notes
        self.save_pipe(p); return True

    def record_payment(self, url: str, usd: float = 0, crypto: str = "") -> bool:
        p = self.load_pipe()
        if url not in p: return False
        p[url]["status"] = "paid"; p[url]["earnings_usd"] = usd
        p[url]["earnings_crypto"] = crypto; p[url]["last_touched"] = time.time()
        self.save_pipe(p); return True

    def pipe_stats(self) -> dict:
        p = self.load_pipe()
        s = {"total": len(p), "by_status": {}, "total_earnings": 0, "by_source": {}, "by_niche": {}}
        for url, d in p.items():
            st = d.get("status", "new")
            s["by_status"][st] = s["by_status"].get(st, 0) + 1
            src = d.get("source", "?")
            s["by_source"][src] = s["by_source"].get(src, 0) + 1
            if st == "paid": s["total_earnings"] += d.get("earnings_usd", 0)
        return s
