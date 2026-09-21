"""Quality gates — pure functions, fully testable, ruthless filtering."""
from __future__ import annotations
import re
import time
from typing import Tuple, List
from models import Lead

# ─── Patterns ─────────────────────────────────────────────────

HIRING_PREFIX = re.compile(
    r"^\s*\[\s*(HIRING|Hire|TASK|Task|PAID|Paid|Bounty|Need|WANTED)\s*\]", re.I)

OFFERING = re.compile(
    r"\[\s*(For\s*Hire|FORHIRE|Offer|Available|Hire\s*Me)\s*\]|"
    r"for hire|i'm available|commissions open|offering my services", re.I)

QUESTION = re.compile(
    r"^(how|what|why|where|when|who|is there|are there|anyone|should i|can i|which|"
    r"tips?|advice|thoughts?|are youtube|people who|would you|have you|what's|whats|"
    r"is freelancing|reality of|let's talk)\b", re.I)

BLACKLIST = re.compile(
    r"giveaway|airdrop|scam|seed phrase|wallet recovery|private key|"
    r"bit\.ly|tinyurl|cut\.ly|shorturl|recover my (?:eth|btc|wallet)|"
    r"lost eth account|free money|earn \$\d+/?day|get rich|passive income|"
    r"mlm|pyramid|nft giveaway", re.I)

LANDING = re.compile(
    r"reddit\.com/r/\w+/?$|laborx\.com/?$|cryptotask\.org/?$|cryptwerk\.com/?$", re.I)

PAY_PATTERNS = [
    re.compile(r"\$\s?\d[\d,]*", re.I),
    re.compile(r"\b\d+\s*(?:btc|eth|usdt|usdc|xmr|sol)\b", re.I),
    re.compile(r"\b(paypal|venmo|cashapp|crypto|paid|payment|will pay|budget|salary|hourly|per hour)\b", re.I),
]

HIRE_SIGNALS = [
    re.compile(r"\b(looking for|need someone|need a|hire|hiring|seeking|will pay|task|gig|freelance)\b", re.I),
    re.compile(r"\b(remote|worldwide|anywhere|global)\b", re.I),
]

REFERRAL_LINKS = re.compile(r"hubs\.l[iy]|linktr\.ee|beacons\.ai|stan\.store", re.I)


def quality_gate(lead: Lead, max_age_hours: float = 72.0, min_budget_usd: float = 5.0) -> Tuple[bool, int, list, list]:
    """Ruthless filter. Returns (passes, score, budget_signals, payment_signals)."""
    text = f"{lead.title}\n{lead.snippet}".strip()

    # Hard drops
    if LANDING.search(lead.url): return False, 0, [], []
    if OFFERING.search(lead.title): return False, 0, [], []
    if lead.created_utc and (time.time() - lead.created_utc) / 3600 > max_age_hours: return False, 0, [], []
    if BLACKLIST.search(text): return False, 0, [], []
    if QUESTION.search(lead.title): return False, 0, [], []

    has_flair = bool(HIRING_PREFIX.search(lead.title))

    # Payment signal required (unless [HIRING] flair)
    pay_hits = [p.search(text).group(0) for p in PAY_PATTERNS if p.search(text)]
    if not pay_hits and not has_flair: return False, 0, [], []

    # Hiring signal required
    hiring_hits = sum(1 for p in HIRE_SIGNALS if p.search(text))
    if hiring_hits == 0: return False, 0, [], []

    # Budget signals
    budget = []
    for m in re.finditer(r"\$\s?(\d[\d,]*(?:\.\d+)?)", text):
        try:
            amt = float(m.group(1).replace(",", ""))
            if amt >= min_budget_usd: budget.append(f"${amt:.0f}")
        except: pass
    for m in re.finditer(r"\b(\d+(?:\.\d+)?)\s*(btc|eth|usdt|usdc|xmr|sol)\b", text, re.I):
        budget.append(m.group(0).strip())
    recurring = re.search(r"\b(hourly|per\s+hour|/hr|/hour|per\s+week|per\s+month|salary|monthly|weekly)\b", text, re.I)
    if not budget and not recurring and not has_flair: return False, 0, [], []

    # ─── Score ───
    s = 30
    s += min(len(pay_hits) * 5, 20)
    s += min(hiring_hits * 6, 18)
    s += min(len(budget) * 4, 12)
    if has_flair: s += 15
    # Recency
    if lead.created_utc:
        age_h = (time.time() - lead.created_utc) / 3600
        if age_h <= 6: s += 15
        elif age_h <= 24: s += 10
        elif age_h <= 48: s += 5
        # Lead aging: decay 5 pts per 12h after first 48h
        if age_h > 48: s -= int((age_h - 48) / 12) * 5
    # Budget bonus
    for b in budget:
        m = re.match(r"\$(\d+)", b)
        if m:
            amt = int(m.group(1))
            if amt >= 1500: s += 8
            elif amt >= 300: s += 5
            elif amt >= 50: s += 3
    # Comment count boost (active discussion = real gig)
    if lead.comment_count >= 10: s += 15
    elif lead.comment_count >= 5: s += 10
    elif lead.comment_count >= 1: s += 3
    # Anti-scam: low karma / new account penalty
    if lead.karma > 0 and lead.karma < 100: s -= 15
    if lead.account_age_days > 0 and lead.account_age_days < 30: s -= 10
    # Referral link penalty
    if REFERRAL_LINKS.search(text): s -= 20

    return True, max(0, min(100, s)), budget, pay_hits
