"""Bitcointalk bounties source — HTML scrape of board 73 (Bounties Altcoins)."""
from __future__ import annotations
import logging
import re
import time
from typing import List
from ..filters import Lead
from ..anon import session_for

log = logging.getLogger("leadfinder.bitcointalk")


def scan(cfg: dict, anon_cfg: dict) -> List[Lead]:
    if not cfg.get("enabled", True):
        return []
    board_id = cfg.get("board_id", 73)
    mode = anon_cfg.get("anonymity", "direct")
    tor_socks = anon_cfg.get("tor_socks", "socks5://127.0.0.1:9050")
    session = session_for(mode, tor_socks)

    leads: List[Lead] = []
    for page in range(0, 3):
        url = f"https://bitcointalk.org/index.php?board={board_id}.{page*40}"
        try:
            r = session.get(url, timeout=20)
            if r.status_code != 200:
                continue
            html = r.text
        except Exception as e:
            log.warning("bitcointalk %s -> %s", url, e)
            continue

        # Each thread: <a href="https://bitcointalk.org/index.php?topic=NNN.NN" ...>Title</a>
        for m in re.finditer(
            r'<a[^>]+href="(https://bitcointalk\.org/index\.php\?topic=\d+\.\d+)"[^>]*>([^<]+)</a>',
            html,
        ):
            turl = m.group(1).split(".0")[0] + ".0"
            title = re.sub(r"\s+", " ", m.group(2)).strip()
            if not title or title.lower().startswith("re:"):
                continue
            leads.append(Lead(
                title=title,
                url=turl,
                source="bitcointalk:bounties",
                snippet="",
                created_utc=time.time() - page * 3600 * 6,  # rough ordering
            ))
        time.sleep(5)
    return leads
