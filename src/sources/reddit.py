"""Source: Reddit — OAuth search + RSS fallback."""
from __future__ import annotations
import base64
import json
import logging
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import List
from models import Lead
from config import Config

log = logging.getLogger("leadfinder.sources.reddit")
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:122.0) Gecko/20100101 Firefox/122.0"
_token = None
_token_expiry = 0


def _get_oauth(cfg) -> str | None:
    global _token, _token_expiry
    if _token and time.time() < _token_expiry - 60: return _token
    cid, csec = cfg.reddit_client_id, cfg.reddit_client_secret
    if not cid or not csec: return None
    auth = base64.b64encode(f"{cid}:{csec}".encode()).decode()
    data = urllib.parse.urlencode({
        "grant_type": "password",
        "username": cfg.reddit_username,
        "password": cfg.reddit_password,
    }).encode()
    try:
        req = urllib.request.Request("https://www.reddit.com/api/v1/access_token",
            data=data, headers={"User-Agent": "leadfinder/3.5", "Authorization": f"Basic {auth}"})
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read())
            _token = d.get("access_token")
            _token_expiry = time.time() + d.get("expires_in", 3600)
            log.info("Reddit OAuth token acquired")
            return _token
    except Exception as e:
        log.warning("Reddit OAuth failed: %s", e)
        return None


def _http_get(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _parse_rss(xml: str) -> List[Lead]:
    leads = []
    try: root = ET.fromstring(xml)
    except: return leads
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall("atom:entry", ns):
        t_el = entry.find("atom:title", ns)
        title = (t_el.text or "").strip() if t_el is not None else ""
        l_el = entry.find("atom:link", ns)
        href = l_el.get("href", "") if l_el is not None else ""
        c_el = entry.find("atom:content", ns)
        c_html = (c_el.text or "") if c_el is not None else ""
        c_text = re.sub(r"<[^>]+>", " ", c_html)
        c_text = re.sub(r"&amp;", "&", c_text)
        c_text = re.sub(r"&lt;|&gt;|&quot;|&#39;", "", c_text)
        c_text = re.sub(r"#32;", " ", c_text)
        c_text = re.sub(r"\s+", " ", c_text).strip()
        p_el = entry.find("atom:published", ns)
        created = 0.0
        if p_el is not None and p_el.text:
            try:
                from datetime import datetime
                created = datetime.fromisoformat(p_el.text.replace("Z", "+00:00")).timestamp()
            except: pass
        sub_m = re.search(r"/r/(\w+)/", href)
        sub = sub_m.group(1) if sub_m else "reddit"
        if title and href:
            leads.append(Lead(title=title, url=href, source=f"reddit:r/{sub}",
                            snippet=c_text[:1500], created_utc=created))
    return leads


def scan(cfg: Config) -> List[Lead]:
    leads: List[Lead] = []
    sleep_s = cfg.scanner.get("sleep_between_requests", 2.0)

    # Try OAuth search (5 queries = 5 requests, covers ALL subs)
    token = _get_oauth(cfg)
    if token:
        queries = cfg.reddit.get("search_queries", ["[Hiring]", "[TASK]"])
        for q in queries:
            url = f"https://oauth.reddit.com/search?q={urllib.parse.quote(q)}&sort=new&t=week&limit=100"
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": "leadfinder/3.5", "Authorization": f"Bearer {token}"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    data = json.loads(r.read())
                children = data.get("data", {}).get("children", [])
                log.info("OAuth search '%s' -> %d", q, len(children))
                for c in children:
                    pd = c.get("data", {})
                    leads.append(Lead(
                        title=pd.get("title", ""),
                        url=f"https://www.reddit.com{pd.get('permalink', '')}",
                        source=f"reddit:r/{pd.get('subreddit', '')}",
                        snippet=(pd.get("selftext", "") or "")[:1500],
                        author=pd.get("author", "") or "",
                        created_utc=float(pd.get("created_utc", 0) or 0),
                        karma=pd.get("author_karma", 0) or 0,
                        comment_count=pd.get("num_comments", 0) or 0,
                    ))
            except Exception as e:
                log.warning("OAuth search '%s' -> %s", q, e)
            time.sleep(sleep_s)
        if leads: return leads

    # Fallback: RSS for key subs
    log.info("Falling back to RSS")
    for sub in cfg.reddit.get("rss_subs", ["slavelabour", "Jobs4Bitcoins"]):
        try:
            xml = _http_get(f"https://www.reddit.com/r/{sub}/new/.rss?limit=25")
            results = _parse_rss(xml)
            log.info("r/%s RSS -> %d", sub, len(results))
            leads.extend(results)
        except Exception as e:
            log.warning("r/%s RSS -> %s", sub, e)
        time.sleep(sleep_s)
    return leads
