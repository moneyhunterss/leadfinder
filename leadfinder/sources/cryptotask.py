"""CryptoTask source."""
from __future__ import annotations
import logging
import time
import re
from typing import List
from ..filters import Lead
from ..anon import session_for

log = logging.getLogger("leadfinder.cryptotask")


def scan(cfg: dict, anon_cfg: dict) -> List[Lead]:
    if not cfg.get("enabled", True):
        return []
    mode = anon_cfg.get("anonymity", "direct")
    tor_socks = anon_cfg.get("tor_socks", "socks5://127.0.0.1:9050")
    session = session_for(mode, tor_socks)
    leads: List[Lead] = []
    try:
        r = session.get("https://cryptotask.org/api/v1/offers?limit=50&filter=latest", timeout=15)
        if r.status_code == 200 and r.headers.get("content-type","").startswith("application/json"):
            for o in r.json().get("offers", []) or r.json().get("items", []):
                leads.append(Lead(
                    title=o.get("title",""),
                    url=f"https://cryptotask.org/offers/{o.get('id','')}",
                    source="cryptotask",
                    snippet=(o.get("description","") or "")[:500],
                    created_utc=float(o.get("createdAt","") and 0 or 0),
                ))
        else:
            r = session.get("https://cryptotask.org/en/offers", timeout=15)
            if r.status_code == 200:
                for m in re.finditer(r'<a[^>]+href="(/en/offers/[^"]+)"[^>]*>([^<]+)</a>', r.text):
                    leads.append(Lead(
                        title=m.group(2).strip(),
                        url=f"https://cryptotask.org{m.group(1)}",
                        source="cryptotask",
                    ))
    except Exception as e:
        log.warning("cryptotask -> %s", e)
    return leads
