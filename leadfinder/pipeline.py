"""Pipeline tracker — SQLite store for lead pipeline status.

A lead moves through these stages:
    new         — just discovered, no action taken yet
    contacted   — outreach sent
    replied     — prospect replied (DM, comment, email)
    quoted      — sent a quote/proposal
    in_progress — work started
    paid        — work done, payment received
    rejected    — prospect said no / scam / lost
    ghosted     — no reply after 5+ days

Stores per-lead:
    url, title, source, score, first_seen, last_touched,
    status, earnings (USD/crypto), notes
"""
from __future__ import annotations
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS pipeline (
    url TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    score INTEGER DEFAULT 0,
    status TEXT DEFAULT 'new',
    earnings_usd REAL DEFAULT 0,
    earnings_crypto TEXT DEFAULT '',
    first_seen REAL,
    last_touched REAL,
    notes TEXT DEFAULT '',
    outreach_sent TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_pipeline_status ON pipeline(status);
CREATE INDEX IF NOT EXISTS idx_pipeline_source ON pipeline(source);
CREATE INDEX IF NOT EXISTS idx_pipeline_score ON pipeline(score DESC);
"""

VALID_STATUSES = {"new", "contacted", "replied", "quoted", "in_progress", "paid", "rejected", "ghosted"}


@dataclass
class PipelineEntry:
    url: str
    title: str
    source: str
    score: int
    status: str
    earnings_usd: float
    earnings_crypto: str
    first_seen: float
    last_touched: float
    notes: str
    outreach_sent: str


class Pipeline:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def upsert_lead(self, url: str, title: str, source: str, score: int = 0) -> bool:
        """Insert if new. Returns True if newly inserted."""
        now = time.time()
        with self._conn() as c:
            row = c.execute("SELECT url FROM pipeline WHERE url=?", (url,)).fetchone()
            if row:
                # Update score only
                c.execute("UPDATE pipeline SET score=?, title=? WHERE url=?",
                          (score, title, url))
                return False
            c.execute(
                "INSERT INTO pipeline (url,title,source,score,status,first_seen,last_touched) VALUES (?,?,?,?,?,?,?)",
                (url, title, source, score, "new", now, now),
            )
            return True

    def set_status(self, url: str, status: str, *, notes: str = "") -> bool:
        if status not in VALID_STATUSES:
            return False
        with self._conn() as c:
            cur = c.execute(
                "UPDATE pipeline SET status=?, last_touched=?, notes=CASE WHEN ?='' THEN notes ELSE ? END WHERE url=?",
                (status, time.time(), notes, notes, url),
            )
            return cur.rowcount > 0

    def mark_contacted(self, url: str, outreach_text: str = "") -> bool:
        with self._conn() as c:
            cur = c.execute(
                "UPDATE pipeline SET status='contacted', last_touched=?, outreach_sent=? WHERE url=?",
                (time.time(), outreach_text, url),
            )
            return cur.rowcount > 0

    def record_payment(self, url: str, usd: float = 0, crypto: str = "") -> bool:
        with self._conn() as c:
            cur = c.execute(
                "UPDATE pipeline SET status='paid', earnings_usd=?, earnings_crypto=?, last_touched=? WHERE url=?",
                (usd, crypto, time.time(), url),
            )
            return cur.rowcount > 0

    def add_note(self, url: str, note: str) -> bool:
        with self._conn() as c:
            cur = c.execute(
                "UPDATE pipeline SET notes = notes || CASE WHEN notes='' THEN '' ELSE char(10) END || ?, last_touched=? WHERE url=?",
                (note, time.time(), url),
            )
            return cur.rowcount > 0

    def get(self, url: str) -> Optional[PipelineEntry]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM pipeline WHERE url=?", (url,)).fetchone()
            if not row:
                return None
            return PipelineEntry(**dict(row))

    def all(self, status: str | None = None) -> list[PipelineEntry]:
        with self._conn() as c:
            if status:
                rows = c.execute(
                    "SELECT * FROM pipeline WHERE status=? ORDER BY last_touched DESC",
                    (status,),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM pipeline ORDER BY last_touched DESC LIMIT 200"
                ).fetchall()
            return [PipelineEntry(**dict(r)) for r in rows]

    def stats(self) -> dict:
        with self._conn() as c:
            counts = {}
            for status in VALID_STATUSES:
                row = c.execute(
                    "SELECT COUNT(*) n FROM pipeline WHERE status=?", (status,)
                ).fetchone()
                counts[status] = row["n"]
            # Earnings totals
            row = c.execute(
                "SELECT COALESCE(SUM(earnings_usd),0) total_usd, COUNT(*) n_paid FROM pipeline WHERE status='paid'"
            ).fetchone()
            counts["total_earnings_usd"] = row["total_usd"] or 0
            counts["n_paid"] = row["n_paid"]
            # By source
            src_rows = c.execute(
                "SELECT source, COUNT(*) n, COALESCE(SUM(earnings_usd),0) usd FROM pipeline GROUP BY source ORDER BY n DESC"
            ).fetchall()
            counts["by_source"] = [{"source": r["source"], "n": r["n"], "usd": r["usd"]} for r in src_rows]
            return counts
