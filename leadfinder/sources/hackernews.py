"""Hacker News source — free Algolia API, no auth."""
from __future__ import annotations
import logging
import time
from typing import List
from ..filters import Lead
from ..anon import session_for

log = logging.getLogger("leadfinder.hn")

BASE = "https://hn.algolia.com/api/v1"


def _fetch(session, path: str, params: dict) -> List[dict]:
    try:
        r = session.get(f"{BASE}/{path}", params=params, timeout=15)
        if r.status_code != 200:
            log.warning("hn %s -> %s", path, r.status_code)
            return []
        return r.json().get("hits", [])
    except Exception as e:
        log.warning("hn %s -> %s", path, e)
        return []


def scan(cfg: dict, anon_cfg: dict) -> List[Lead]:
    if not cfg.get("enabled", True):
        return []
    mode = anon_cfg.get("anonymity", "direct")
    tor_socks = anon_cfg.get("tor_socks", "socks5://127.0.0.1:9050")
    session = session_for(mode, tor_socks)

    leads: List[Lead] = []
    # 1) "Ask HN: Who is hiring?" stories — get the latest monthly thread
    if cfg.get("include_who_is_hiring", True):
        hits = _fetch(session, "search", {
            "query": "Ask HN: Who is hiring",
            "tags": "story",
            "hitsPerPage": 3,
        })
        for h in hits:
            story_id = h.get("objectID")
            if not story_id:
                continue
            # Fetch top comments on that story — each comment is a job post
            kids = _fetch(session, "search", {
                "tags": "comment",
                "storyID": story_id,
                "hitsPerPage": 50,
            })
            for k in kids:
                ctext = (k.get("comment_text") or "")[:600]
                cauthor = k.get("author") or ""
                ctime = k.get("created_at_i") or 0
                leads.append(Lead(
                    title=(k.get("story_title") or "HN comment"),
                    url=f"https://news.ycombinator.com/item?id={k.get('objectID','')}",
                    source="hackernews:who_is_hiring",
                    snippet=ctext,
                    author=cauthor,
                    created_utc=float(ctime),
                ))
            time.sleep(1)

    # 2) Recent posts tagged "freelance / contract / remote"
    for q in ["freelance remote contract", "freelance gig paid", "looking for developer freelance"]:
        hits = _fetch(session, "search_by_date", {
            "tags": "story",
            "query": q,
            "hitsPerPage": 25,
        })
        for h in hits:
            leads.append(Lead(
                title=h.get("title") or "",
                url=h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID','')}",
                source="hackernews:search",
                snippet=(h.get("story_text") or "")[:500],
                author=h.get("author") or "",
                created_utc=float(h.get("created_at_i") or 0),
            ))
        time.sleep(1)

    return leads
