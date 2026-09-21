"""Source: Hacker News Algolia (free, no auth)."""
from __future__ import annotations
import json
import logging
import urllib.request
from typing import List
from models import Lead
from config import Config

log = logging.getLogger("leadfinder.sources.hn")


def scan(cfg: Config) -> List[Lead]:
    if not cfg.hn.get("enabled", True): return []
    leads = []
    try:
        url = "https://hn.algolia.com/api/v1/search?query=Ask+HN+Who+is+hiring&tags=story&hitsPerPage=3"
        req = urllib.request.Request(url, headers={"User-Agent": "leadfinder/3.5"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        for h in data.get("hits", []):
            title = h.get("title", "")
            if "who is hiring" not in title.lower() or "wants to be hired" in title.lower(): continue
            sid = h.get("objectID")
            cmt_url = f"https://hn.algolia.com/api/v1/search?tags=comment&storyID={sid}&hitsPerPage=50"
            with urllib.request.urlopen(urllib.request.Request(cmt_url, headers={"User-Agent": "leadfinder/3.5"}), timeout=20) as r2:
                cdata = json.loads(r2.read())
            for k in cdata.get("hits", []):
                leads.append(Lead(
                    title=(k.get("story_title") or "HN Who's Hiring")[:200],
                    url=f"https://news.ycombinator.com/item?id={k.get('objectID', '')}",
                    source="hackernews",
                    snippet=(k.get("comment_text") or "")[:1500],
                    author=k.get("author") or "",
                    created_utc=float(k.get("created_at_i") or 0),
                ))
            break
    except Exception as e:
        log.warning("HN -> %s", e)
    return leads
