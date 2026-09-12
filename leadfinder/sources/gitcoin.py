"""Gitcoin bounties source."""
from __future__ import annotations
import logging
import time
from typing import List
from ..filters import Lead
from ..anon import session_for

log = logging.getLogger("leadfinder.gitcoin")


def scan(cfg: dict, anon_cfg: dict) -> List[Lead]:
    if not cfg.get("enabled", True):
        return []
    mode = anon_cfg.get("anonymity", "direct")
    tor_socks = anon_cfg.get("tor_socks", "socks5://127.0.0.1:9050")
    session = session_for(mode, tor_socks)
    leads: List[Lead] = []
    # Gitcoin's bounty API endpoint — keep it lenient on schema
    candidates = [
        "https://bounty.api.v1.gitcoin.co/bounties?limit=50&order_by=-created_on",
        "https://gitcoin.co/api/v0.1/bounties/?limit=50&order_by=-created_on",
    ]
    for url in candidates:
        try:
            r = session.get(url, timeout=15)
            if r.status_code == 200:
                data = r.json()
                items = data if isinstance(data, list) else data.get("results", data.get("items", []))
                for b in items:
                    leads.append(Lead(
                        title=(b.get("title") or b.get("metadata",{}).get("title",""))[:200],
                        url=b.get("url","") or b.get("github_url","") or f"https://gitcoin.co/bounties/{b.get('pk','')}",
                        source="gitcoin",
                        snippet=(b.get("issue_description","") or "")[:500],
                        created_utc=float(b.get("created_on","") and __import__('dateutil').parser.isoparse(b["created_on"]).timestamp() or 0),
                    ))
                if items:
                    break
        except Exception as e:
            log.warning("gitcoin %s -> %s", url, e)
        time.sleep(2)
    return leads
