"""Reddit source — uses the public .json endpoint (no auth, no API key).

Endpoint patterns:
  https://www.reddit.com/r/{sub}/new.json?limit=N
  https://www.reddit.com/r/{sub}/search.json?q=...&restrict_sr=1&sort=new&t=week
  https://www.reddit.com/user/me/m/lucky/r/{multi}/ (needs OAuth)

Rate limit: 10 QPM unauthenticated, 100 QPM with OAuth.
This module throttles to 1 req / 6 s per sub, well below the limit.
"""
from __future__ import annotations
import time
import logging
from typing import List
from ..filters import Lead
from ..anon import session_for

log = logging.getLogger("leadfinder.reddit")


def _paginate_json(session, url: str, *, limit: int = 25) -> List[dict]:
    """Fetch a reddit .json URL, return list of post dicts. Empty on failure."""
    try:
        r = session.get(url, timeout=15)
        if r.status_code != 200:
            log.warning("reddit %s -> %s", url, r.status_code)
            return []
        data = r.json()
        return data.get("data", {}).get("children", [])
    except Exception as e:
        log.warning("reddit %s -> %s", url, e)
        return []


def scan(cfg: dict, anon_cfg: dict) -> List[Lead]:
    """Scan all configured subreddits. cfg = sources.reddit block."""
    if not cfg.get("enabled", True):
        return []
    subs = cfg.get("subreddits", [])
    flairs = set(cfg.get("flairs_whitelist", []) or [])
    sort = cfg.get("sort", "new")
    limit = int(cfg.get("limit_per_sub", 25))
    mode = anon_cfg.get("anonymity", "direct")
    tor_socks = anon_cfg.get("tor_socks", "socks5://127.0.0.1:9050")
    session = session_for(mode, tor_socks)

    leads: List[Lead] = []
    for sub in subs:
        url = f"https://www.reddit.com/r/{sub}/{sort}.json?limit={limit}"
        children = _paginate_json(session, url, limit=limit)
        log.info("reddit r/%s -> %d posts", sub, len(children))
        for c in children:
            pd = c.get("data", {})
            title = pd.get("title", "")
            permalink = pd.get("permalink", "")
            full_url = f"https://www.reddit.com{permalink}" if permalink else ""
            snippet = (pd.get("selftext", "") or "")[:500]
            flair = pd.get("link_flair_text", "") or ""
            created = float(pd.get("created_utc", 0) or 0)
            author = pd.get("author", "") or ""
            ncomments = int(pd.get("num_comments", 0) or 0)
            # Optional flair filter
            if flairs and flair and flair.upper() not in {f.upper() for f in flairs}:
                # If flair present but not whitelisted, still keep — let the
                # keyword filter decide. (Flairs are often missing.)
                pass
            leads.append(Lead(
                title=title,
                url=full_url,
                source=f"reddit:r/{sub}",
                snippet=snippet,
                author=author,
                created_utc=created,
                flair=flair,
                num_comments=ncomments,
            ))
        time.sleep(6)  # polite throttle — 10 req/min cap
    return leads
