"""Source: Bitcointalk bounties (HTML scrape, polite)."""
from __future__ import annotations
import logging
import re
import time
import urllib.request
from typing import List
from models import Lead
from config import Config

log = logging.getLogger("leadfinder.sources.bt")
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:122.0) Gecko/20100101 Firefox/122.0"


def scan(cfg: Config) -> List[Lead]:
    bt = cfg.bitcointalk
    if not bt.get("enabled", True): return []
    board = bt.get("board_id", 73)
    leads = []
    for page in range(2):
        url = f"https://bitcointalk.org/index.php?board={board}.{page*40}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                html = r.read().decode("utf-8", errors="replace")
            for m in re.finditer(r'index\.php\?topic=(\d+)\.(?:\d+)"[^>]*>([^<]+)<', html):
                title = re.sub(r"\s+", " ", m.group(2)).strip()
                if title and not title.lower().startswith("re:") and len(title) > 5:
                    leads.append(Lead(
                        title=title,
                        url=f"https://bitcointalk.org/index.php?topic={m.group(1)}",
                        source="bitcointalk",
                        created_utc=time.time() - page * 3600 * 12,
                    ))
        except Exception as e:
            log.warning("bitcointalk -> %s", e)
        time.sleep(3)
    return leads
