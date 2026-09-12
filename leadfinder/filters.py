"""Lead filtering + scoring."""
from __future__ import annotations
import re
import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Pattern


@dataclass
class Lead:
    title: str
    url: str
    source: str              # 'reddit:r/slavelabour' / 'hackernews' / 'bitcointalk' / 'laborx' / 'gitcoin'
    snippet: str = ""
    author: str = ""
    score: int = 0
    created_utc: float = 0.0  # epoch
    budget_signals: List[str] = field(default_factory=list)
    payment_signals: List[str] = field(default_factory=list)
    flair: str = ""
    num_comments: int = 0
    outreach_draft: str = ""

    @property
    def age_hours(self) -> float:
        if not self.created_utc:
            return 0.0
        return max(0.0, (time.time() - self.created_utc) / 3600.0)

    def as_dict(self) -> Dict:
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "snippet": self.snippet,
            "author": self.author,
            "score": self.score,
            "age_hours": round(self.age_hours, 1),
            "budget_signals": self.budget_signals,
            "payment_signals": self.payment_signals,
            "flair": self.flair,
            "num_comments": self.num_comments,
            "outreach_draft": self.outreach_draft,
        }


def _compile(patterns: List[str]) -> List[Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


def score_lead(
    text: str,
    *,
    whitelist: List[str],
    blacklist: List[str],
    payment_signals: List[str],
    flair: str = "",
    created_utc: float = 0.0,
    max_age_hours: float = 168.0,
) -> tuple[int, List[str], List[str]]:
    """Return (score, budget_matches, payment_matches). 0-100."""
    wl = _compile(whitelist)
    bl = _compile(blacklist)
    pay = _compile(payment_signals)

    # Blacklist veto
    for p in bl:
        if p.search(text):
            return 0, [], []

    # White matches
    wl_hits = sum(1 for p in wl if p.search(text))
    # Payment matches
    pay_hits = [p.pattern for p in pay if p.search(text)]

    # Budget signals — collect matched text
    budget_hits = []
    for p in wl:
        m = p.search(text)
        if m and ("\\d" in p.pattern or "btc" in p.pattern.lower() or "eth" in p.pattern.lower()):
            budget_hits.append(m.group(0))

    # Base score
    score = 0
    score += min(wl_hits * 8, 40)
    score += min(len(pay_hits) * 6, 30)
    score += min(len(budget_hits) * 5, 15)

    # Flair bonus
    flair_str = (flair or "").upper()
    if flair_str in {"TASK", "HIRE", "HIRING", "PAID", "PAID TASK", "OFFERING", "FOR HIRE"}:
        score += 10
    if "HIRE" in flair_str or "TASK" in flair_str:
        score += 5

    # Recency bonus
    if created_utc:
        age_h = max(0.0, (time.time() - created_utc) / 3600.0)
        if age_h <= 24:
            score += 15
        elif age_h <= 72:
            score += 8
        elif age_h <= max_age_hours:
            score += 2
        else:
            score -= 10  # too old

    return max(0, min(100, score)), budget_hits, pay_hits
