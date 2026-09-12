"""Outreach draft generator.

Generates a short cold-message template per lead, tuned to the source.
Does NOT send anything — you copy/paste manually. This keeps you human
and avoids platform bot-detection.
"""
from __future__ import annotations
from .filters import Lead


def generate_draft(lead: Lead, *, tone: str = "direct", max_words: int = 80, include_pricing_prompt: bool = True) -> str:
    """Compose a 60-80 word outreach message tailored to the lead."""
    title = lead.title.strip() or "your task"
    snippet = (lead.snippet or "").strip().replace("\n", " ")[:200]
    src = lead.source

    # Pick a greeting by source
    if src.startswith("reddit:"):
        greet = "Hey — saw your post on Reddit"
    elif src.startswith("hackernews"):
        greet = "Hi — saw your HN comment"
    elif src == "bitcointalk:bounties":
        greet = "Hi — saw your bounty thread"
    elif src == "laborx":
        greet = "Hi — saw your LaborX listing"
    elif src == "gitcoin":
        greet = "Hey — saw your Gitcoin bounty"
    elif src == "cryptotask":
        greet = "Hi — saw your CryptoTask offer"
    else:
        greet = "Hi"

    # Hook — reference the task title
    msg = f"{greet} (\"{title[:80]}\"). "
    if snippet:
        msg += f"You mentioned: \"{snippet[:100]}\...\". I can do this. "
    else:
        msg += "I can take this on. "

    # Capability statement
    msg += "I've done similar work recently — happy to share a quick sample or do a 10-min proof-of-concept before any commitment. "

    # Payment + close
    if include_pricing_prompt:
        if lead.payment_signals:
            msg += f"OK to be paid in {', '.join(lead.payment_signals[:2])}. "
        else:
            msg += "Open to crypto (BTC/ETH/USDT) or PayPal — your call. "
        msg += "What's your budget and timeline? I can start today."
    else:
        msg += "What's your timeline? Can start today."

    # Trim to max_words
    words = msg.split()
    if len(words) > max_words:
        msg = " ".join(words[:max_words]) + "..."
    return msg
