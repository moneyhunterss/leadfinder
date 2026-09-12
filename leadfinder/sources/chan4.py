"""4chan /g/ + /biz/ + /wsr/ source — public 4catalog API.

4chan has a public JSON API at https://a.4cdn.org/board/threads.json — no
auth, no rate limit issues. We scan /g/ (tech), /biz/ (crypto/business),
and /wsr/ (work/hiring threads).
"""
from __future__ import annotations
import logging
import re
import time
from typing import List
from ..filters import Lead
from ..anon import session_for

log = logging.getLogger("leadfinder.4chan")

BOARDS = ["g", "biz", "wsr"]


def scan(cfg: dict, anon_cfg: dict) -> List[Lead]:
    if not cfg.get("enabled", True):
        return []
    mode = anon_cfg.get("anonymity", "direct")
    tor_socks = anon_cfg.get("tor_socks", "socks5://127.0.0.1:9050")
    session = session_for(mode, tor_socks)
    session.headers.update({"Accept": "application/json"})

    leads: List[Lead] = []
    for board in BOARDS:
        # Catalog endpoint — returns list of pages, each with threads
        url = f"https://a.4cdn.org/{board}/catalog.json"
        try:
            r = session.get(url, timeout=15)
            if r.status_code != 200:
                continue
            pages = r.json()
            for page in pages[:3]:  # only first 3 pages (10 threads each)
                for t in page.get("threads", [])[:15]:
                    sub = (t.get("sub") or "").strip()
                    com = (t.get("com") or "").strip()
                    # Strip HTML from comment
                    com = re.sub(r"<[^>]+>", " ", com)
                    com = re.sub(r"&gt;", ">", com)
                    com = re.sub(r"&lt;", "<", com)
                    com = re.sub(r"&amp;", "&", com)
                    com = re.sub(r"&quot;", '"', com)
                    com = re.sub(r"&#039;", "'", com)
                    com = re.sub(r"\s+", " ", com).strip()
                    title = sub or com[:80] or "(no title)"
                    no = t.get("no")
                    if not no:
                        continue
                    url_str = f"https://boards.4chan.org/{board}/thread/{no}"
                    created = float(t.get("time", 0) or 0)
                    leads.append(Lead(
                        title=title[:200],
                        url=url_str,
                        source=f"4chan:/{board}/",
                        snippet=com[:1500],
                        created_utc=created,
                    ))
        except Exception as e:
            log.warning("4chan /%s/ -> %s", board, e)
        time.sleep(1)
    return leads
