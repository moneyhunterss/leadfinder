"""Niche detection — keyword-based, handles edge cases."""
from __future__ import annotations
import re

# Order matters: more specific niches checked first
NICHES_ORDERED = [
    ("motion", r"(motion\s+graphics|motion\s+design|kinetic|3d\s+anim|vfx|compositing|after\s+effects)"),
    ("video", r"(video\s+edit|shorts|reels|tiktok|youtube|premiere|davinci|final\s+cut)"),
    ("devops", r"(devops|docker|kubernetes|terraform|aws|gcp|azure|ci/cd|infrastructure|linux|sysadmin)"),
    ("dev", r"(python|javascript|developer|code|script|app|web|api|bot|automation|react|node|next\.?js|scrap|solidity|smart\s+contract)"),
    ("design", r"(logo|design|brand|figma|graphic|photoshop|illustration|identity|branding)"),
    ("writing", r"(writer|writing|article|blog|content|copy|proofread|ghostwriter|transcription|transcrib)"),
    ("sales", r"(sales|cold\s+call|appointment\s+set|lead\s+gen|telemarketing|outbound)"),
    ("va", r"(virtual\s+assistant|\bva\b|admin|schedule|email|inbox|customer\s+support|data\s+entry|appointment)"),
    ("crypto", r"(crypto|btc|eth|web3|nft|discord|defi|blockchain|token|staking)"),
]

COMPILED = [(n, re.compile(p, re.I)) for n, p in NICHES_ORDERED]


def detect_niche(text: str) -> str:
    """Detect niche. Checks specific niches before general ones."""
    for niche, pattern in COMPILED:
        if pattern.search(text):
            return niche
    return "general"
