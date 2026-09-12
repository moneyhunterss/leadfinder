"""LaborX source — public listing page."""
from __future__ import annotations
import logging
import time
from typing import List
from ..filters import Lead
from ..anon import session_for

log = logging.getLogger("leadfinder.laborx")


def scan(cfg: dict, anon_cfg: dict) -> List[Lead]:
    if not cfg.get("enabled", True):
        return []
    mode = anon_cfg.get("anonymity", "direct")
    tor_socks = anon_cfg.get("tor_socks", "socks5://127.0.0.1:9050")
    session = session_for(mode, tor_socks)
    leads: List[Lead] = []
    try:
        r = session.get("https://laborx.com/api/v1/jobs?limit=50&sort=latest", timeout=15)
        if r.status_code == 200 and r.headers.get("content-type","").startswith("application/json"):
            for j in r.json().get("jobs", []) or r.json().get("items", []):
                leads.append(Lead(
                    title=j.get("title",""),
                    url=f"https://laborx.com/jobs/{j.get('id','')}",
                    source="laborx",
                    snippet=(j.get("description") or "")[:500],
                    created_utc=float(j.get("createdAt", 0) if isinstance(j.get("createdAt"), (int,float)) else 0),
                ))
        else:
            # Fallback: HTML scrape
            r = session.get("https://laborx.com/jobs", timeout=15)
            log.info("laborx fallback HTML status %s", r.status_code)
    except Exception as e:
        log.warning("laborx -> %s", e)
    return leads
