"""Lead model + tier classification."""
from __future__ import annotations
import re
import time
from dataclasses import dataclass, field
from typing import List


@dataclass
class Lead:
    title: str
    url: str
    source: str
    snippet: str = ""
    author: str = ""
    score: int = 0
    created_utc: float = 0.0
    budget_signals: List[str] = field(default_factory=list)
    payment_signals: List[str] = field(default_factory=list)
    niche: str = ""
    tier: str = ""
    outreach_draft: str = ""
    karma: int = 0
    account_age_days: int = 0
    comment_count: int = 0
    notified: bool = False

    @property
    def age_hours(self) -> float:
        return max(0.0, (time.time() - self.created_utc) / 3600.0) if self.created_utc else 0.0

    def as_dict(self) -> dict:
        return {
            "title": self.title, "url": self.url, "source": self.source,
            "snippet": self.snippet[:500], "author": self.author, "score": self.score,
            "budget_signals": self.budget_signals, "payment_signals": self.payment_signals,
            "niche": self.niche, "tier": self.tier,
            "age_hours": round(self.age_hours, 1),
            "outreach_draft": self.outreach_draft,
            "karma": self.karma, "account_age_days": self.account_age_days,
            "comment_count": self.comment_count,
        }


def classify_tier(budget_signals: list[str]) -> str:
    """micro ($5-50), standard ($50-300), pro ($300-1500), elite ($1500+)."""
    max_usd = 0
    for sig in budget_signals:
        m = re.match(r"\$(\d+)", sig)
        if m: max_usd = max(max_usd, int(m.group(1)))
    for sig in budget_signals:
        m = re.match(r"(\d+(?:\.\d+)?)\s*(btc|eth|usdt|usdc|xmr|sol)", sig, re.I)
        if m:
            rates = {"btc": 50000, "eth": 2000, "usdt": 1, "usdc": 1, "xmr": 150, "sol": 100}
            max_usd = max(max_usd, int(float(m.group(1)) * rates.get(m.group(2).lower(), 50)))
    if max_usd >= 1500: return "elite"
    if max_usd >= 300: return "pro"
    if max_usd >= 50: return "standard"
    if max_usd > 0: return "micro"
    return "unspecified"
