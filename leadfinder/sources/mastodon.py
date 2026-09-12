"""Mastodon / Fediverse search — queries multiple public instances.

Uses the public Mastodon search API v2 on instances that allow public search
without auth: mastodon.social, mas.to, fosstodon.org (dev-focused).
"""
from __future__ import annotations
import logging
import time
from typing import List
from ..filters import Lead
from ..anon import session_for

log = logging.getLogger("leadfinder.mastodon")

INSTANCES = [
    "https://mastodon.social",
    "https://fosstodon.org",
    "https://hachyderm.io",
]
QUERIES = [
    "freelance paid",
    "hiring freelance",
    "looking for developer",
    "crypto bounty task",
    "remote gig",
]


def scan(cfg: dict, anon_cfg: dict) -> List[Lead]:
    if not cfg.get("enabled", True):
        return []
    mode = anon_cfg.get("anonymity", "direct")
    tor_socks = anon_cfg.get("tor_socks", "socks5://127.0.0.1:9050")
    session = session_for(mode, tor_socks)

    leads: List[Lead] = []
    for inst in INSTANCES:
        for q in QUERIES:
            url = f"{inst}/api/v2/search?q={q}&type=statuses&limit=10"
            try:
                r = session.get(url, timeout=12)
                if r.status_code != 200:
                    continue
                data = r.json()
                for s in data.get("statuses", []):
                    content = (s.get("content") or "")
                    # Strip HTML
                    import re
                    content = re.sub(r"<[^>]+>", " ", content)
                    content = re.sub(r"\s+", " ", content).strip()
                    if not content:
                        continue
                    url_s = s.get("url") or s.get("uri") or ""
                    created = 0.0
                    if s.get("created_at"):
                        try:
                            from datetime import datetime
                            created = datetime.fromisoformat(s["created_at"].replace("Z","+00:00")).timestamp()
                        except Exception:
                            pass
                    leads.append(Lead(
                        title=content[:120],
                        url=url_s,
                        source=f"mastodon:{inst.split('//')[1]}",
                        snippet=content[:1500],
                        author=s.get("account", {}).get("acct", "") if isinstance(s.get("account"), dict) else "",
                        created_utc=created,
                    ))
            except Exception as e:
                log.warning("mastodon %s -> %s", inst, e)
            time.sleep(1)
    return leads
