"""SQLite store with dedup + seen tracking."""
from __future__ import annotations
import sqlite3
import time
from pathlib import Path
from typing import List, Iterable, Optional

from .filters import Lead

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    url TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    snippet TEXT,
    author TEXT,
    score INTEGER,
    age_hours REAL,
    budget_signals TEXT,
    payment_signals TEXT,
    flair TEXT,
    num_comments INTEGER,
    outreach_draft TEXT,
    first_seen REAL,
    last_seen REAL
);
CREATE INDEX IF NOT EXISTS idx_leads_score ON leads(score DESC);
CREATE INDEX IF NOT EXISTS idx_leads_last_seen ON leads(last_seen DESC);
"""


class Store:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def upsert(self, lead: Lead) -> bool:
        """Insert or update. Returns True if this is a NEW lead."""
        now = time.time()
        with self._conn() as c:
            row = c.execute("SELECT url FROM leads WHERE url=?", (lead.url,)).fetchone()
            c.execute(
                """INSERT OR REPLACE INTO leads
                   (url,title,source,snippet,author,score,age_hours,budget_signals,
                    payment_signals,flair,num_comments,outreach_draft,first_seen,last_seen)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    lead.url, lead.title, lead.source, lead.snippet, lead.author,
                    lead.score, lead.age_hours, ",".join(lead.budget_signals),
                    ",".join(lead.payment_signals), lead.flair, lead.num_comments,
                    lead.outreach_draft,
                    row["first_seen"] if row else now,
                    now,
                ),
            )
            return row is None

    def upsert_many(self, leads: Iterable[Lead]) -> List[Lead]:
        new_leads: List[Lead] = []
        for l in leads:
            if self.upsert(l):
                new_leads.append(l)
        return new_leads

    def all(self, *, min_score: int = 0, limit: Optional[int] = None) -> List[Lead]:
        with self._conn() as c:
            q = "SELECT * FROM leads WHERE score >= ? ORDER BY score DESC, last_seen DESC"
            params = [min_score]
            if limit:
                q += " LIMIT ?"
                params.append(limit)
            rows = c.execute(q, params).fetchall()
            return [_row_to_lead(r) for r in rows]

    def recent(self, since_ts: float, *, min_score: int = 0) -> List[Lead]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM leads WHERE last_seen >= ? AND score >= ? ORDER BY score DESC, last_seen DESC",
                (since_ts, min_score),
            ).fetchall()
            return [_row_to_lead(r) for r in rows]

    def count_by_source(self) -> dict:
        with self._conn() as c:
            rows = c.execute("SELECT source, COUNT(*) n FROM leads GROUP BY source").fetchall()
            return {r["source"]: r["n"] for r in rows}


def _row_to_lead(r) -> Lead:
    return Lead(
        title=r["title"],
        url=r["url"],
        source=r["source"],
        snippet=r["snippet"] or "",
        author=r["author"] or "",
        score=r["score"],
        created_utc=time.time() - (r["age_hours"] or 0) * 3600.0,
        budget_signals=[s for s in (r["budget_signals"] or "").split(",") if s],
        payment_signals=[s for s in (r["payment_signals"] or "").split(",") if s],
        flair=r["flair"] or "",
        num_comments=r["num_comments"] or 0,
        outreach_draft=r["outreach_draft"] or "",
    )
