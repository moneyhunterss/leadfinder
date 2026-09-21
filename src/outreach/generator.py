"""Per-niche outreach generator — high-conversion, human, under 800 chars."""
from __future__ import annotations
import re
from models import Lead
from config import Config


def generate(lead: Lead, niche: str, cfg: Config) -> str:
    url = cfg.portfolio.get("url", "https://moneyhunterss.github.io/")
    title = lead.title.strip()[:70]
    snip = (lead.snippet or "").strip().replace("\n", " ")[:120]
    budget = ", ".join(lead.budget_signals[:2]) if lead.budget_signals else ""

    # Quote the hiring phrase
    quote = ""
    for pat in [r"looking\s+for\s+[^.\n]{5,80}", r"need\s+(?:someone|a)[^.\n]{5,80}", r"will\s+pay[^.\n]{5,80}"]:
        m = re.search(pat, snip + " " + (lead.snippet or ""), re.I)
        if m: quote = m.group(0).strip()[:100]; break

    msg = f'Hey — saw your post "{title}".\n\n'
    msg += f'You wrote: "{quote}..." — I can do this.\n\n' if quote else "I can take this on.\n\n"

    # Niche-specific proof + free sample offer
    proofs = {
        "writing": f"I'll write 200 words on your topic right now — free, before any commitment. Portfolio: {url}",
        "design": f"I'll mock up 1 logo concept in the next 2 hours — free. Portfolio: {url}",
        "video": f"Send me 30s of raw footage — I'll cut a 15s sample so you can judge my pacing. Portfolio: {url}",
        "motion": f"Send me 1 frame — I'll animate it as a free proof of concept. Portfolio: {url}",
        "dev": f"I'll open a PR with a working demo within 24h — free. Portfolio: {url}",
        "devops": f"I'll audit your current setup and send 3 specific fixes — free. Portfolio: {url}",
        "va": f"I'll do a paid 2-hour trial — you only commit after seeing output. Portfolio: {url}",
        "sales": f"I'll run 5 test calls and send you the recordings — free. Portfolio: {url}",
        "crypto": f"I'll send a test transaction or audit your contract — free proof. Portfolio: {url}",
    }
    msg += proofs.get(niche, f"Portfolio: {url} — free proof-of-concept in 24h.")
    msg += "\n\n"

    if budget: msg += f"Budget: {budget} — workable. "
    else: msg += "What's your budget + timeline? "
    crypto_hits = [p for p in lead.payment_signals if isinstance(p, str) and any(t in p.lower() for t in ("btc", "eth", "usdt", "crypto"))]
    msg += "Crypto or PayPal works. " if not crypto_hits else "OK to be paid in crypto. "
    msg += "Can start today."

    # Trim to 800 chars
    return msg[:800] if len(msg) > 800 else msg
