"""Scan now — uses z-ai web_search as a Reddit proxy (Reddit blocks this server's
datacenter IP). Hits HN Algolia directly. Aggregates, filters, scores, generates
outreach drafts, and writes digest files to /home/z/my-project/download/.

This is the 'right-now' runner. For continuous 24/7 monitoring, install the
leadfinder package on your own machine and run `python -m leadfinder watch`
— your home IP will be able to hit reddit.com directly without needing this
web_search proxy fallback.
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import time
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import List

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("scan_now")

ROOT = Path("/home/z/my-project")
RAW_DIR = ROOT / "research" / "raw"
OUT_DIR = ROOT / "download"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RAW_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Lead:
    title: str
    url: str
    source: str
    snippet: str = ""
    author: str = ""
    score: int = 0
    created_utc: float = 0.0
    budget_signals: List[str] = field(default_factory=list)
    payment_signals: List[str] = field(default_factory=list)
    flair: str = ""
    num_comments: int = 0
    outreach_draft: str = ""

    def as_dict(self):
        return {
            "title": self.title, "url": self.url, "source": self.source,
            "snippet": self.snippet, "author": self.author, "score": self.score,
            "budget_signals": self.budget_signals, "payment_signals": self.payment_signals,
            "age_hours": round(max(0, (time.time()-self.created_utc)/3600), 1) if self.created_utc else 0,
            "outreach_draft": self.outreach_draft,
        }


# Queries to run via web_search (Reddit blocks this server, so we use ZAI search
# as a proxy to find recent matching Reddit posts).
QUERIES = [
    ("reddit:r/slavelabour",     'site:reddit.com r/slavelabour task pay', 3),
    ("reddit:r/slavelabour",     'site:reddit.com r/slavelabour "task" "paid"', 1),
    ("reddit:r/slavelabour",     'site:reddit.com r/slavelabour "[task]" -offer 2025', 7),
    ("reddit:r/slavelabour",     'site:reddit.com r/slavelabour "[offer]" will pay', 3),
    ("reddit:r/Jobs4Bitcoins",   'site:reddit.com r/Jobs4Bitcoins hire task', 7),
    ("reddit:r/Jobs4Bitcoins",   'site:reddit.com r/Jobs4Bitcoins "[task]" -meta', 14),
    ("reddit:r/DigitalCartel",   'site:reddit.com r/DigitalCartel task crypto pay', 7),
    ("reddit:r/forhire",         'site:reddit.com r/forhire hiring freelancer', 3),
    ("reddit:r/forhire",         'site:reddit.com r/forhire "[hiring]" task pay', 3),
    ("reddit:r/forhire",         'site:reddit.com r/forhire "[hiring]" freelance developer pay 2025', 7),
    ("reddit:r/freelance_forhire", 'site:reddit.com/r/freelance_forhire hiring pay', 7),
    ("reddit:r/jobbit",          'site:reddit.com r/jobbit hire pay', 7),
    ("reddit:r/HireaWriter",     'site:reddit.com r/HireaWriter pay article blog', 7),
    ("reddit:r/ProgrammingPromos", 'site:reddit.com r/ProgrammingPromos hire dev build', 14),
    ("reddit:r/EmployedFreelancers", 'site:reddit.com r/EmployedFreelancers hire contract', 7),
    ("reddit:r/copywriting",    'site:reddit.com r/copywriting pay hire writer', 7),
    ("reddit:r/learnpython",     'site:reddit.com r/learnpython pay someone script build task', 7),
    ("reddit:r/datasets",        'site:reddit.com r/datasets hire pay data scraping', 14),
    ("reddit:r/webdev",          'site:reddit.com r/webdev hire freelance pay build', 7),
    ("reddit:r/CryptoCurrency", 'site:reddit.com/r/CryptoCurrency bounty task paid', 7),
    ("reddit:r/ethtrader",      'site:reddit.com/r/ethtrader bounty paid', 14),
    ("generic",                  'freelance gig paid crypto btc eth usdt immediately start', 3),
    ("generic",                  '"paid in crypto" task freelance looking for developer 2025', 14),
    ("laborx",                   'laborx.com crypto freelance task posted today', 7),
    ("gitcoin",                  'gitcoin bounties open 2025 claim ETH reward', 30),
    ("hackernews",               'Ask HN Who is hiring 2026 remote contract freelance', 45),
    ("bitcointalk",              'bitcointalk bounty paid task altcoin 2025', 30),
]

WHITELIST = [
    r"hire", r"hiring", r"looking\s+for", r"need\s+someone", r"need\s+a",
    r"will\s+pay", r"willing\s+to\s+pay", r"paid", r"payment", r"budget",
    r"task", r"gig", r"freelance", r"contract", r"bounty", r"reward",
    r"\$\d+", r"\d+\s*(?:btc|eth|usdt|usdc|xmr|sol)",
]
BLACKLIST = [
    r"giveaway", r"airdrop", r"free\s+money", r"\bscam\b",
    r"free\s+\$", r"earn\s+\$", r"click\s+here", r"referral\s+code",
    r"https://t\.me", r"dm\s+me\s+on\s+instagram",
]
PAYMENT_SIGNALS = [
    r"btc", r"bitcoin", r"\beth\b", r"ethereum", r"usdt", r"usdc",
    r"xmr", r"monero", r"\bsol\b", r"solana", r"paypal", r"venmo",
    r"cashapp", r"\bwise\b", r"payeer", r"crypto", r"cryptocurrency", r"stablecoin",
]


def _compile(pats):
    return [re.compile(p, re.IGNORECASE) for p in pats]


WL = _compile(WHITELIST)
BL = _compile(BLACKLIST)
PAY = _compile(PAYMENT_SIGNALS)


def parse_zai_date(s: str) -> float:
    """Parse dates like 'Jul 13, 2024' or 'May 12, 2026' or '' to epoch."""
    if not s:
        return 0.0
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return time.mktime(time.strptime(s.strip(), fmt))
        except Exception:
            continue
    return 0.0


import hashlib

def _qhash(q: str) -> str:
    return hashlib.md5(q.encode("utf-8")).hexdigest()


def zai_search(query: str, recency_days: int = 7, num: int = 20) -> List[dict]:
    """Call the z-ai web_search CLI and return parsed hits. Cached by query."""
    cache_file = RAW_DIR / f"q_{_qhash(query)}.json"
    # Reuse cache if it exists (avoid re-hitting rate-limited API)
    if cache_file.exists():
        try:
            with open(cache_file) as f:
                data = json.load(f)
            items = data if isinstance(data, list) else data.get("results", data.get("data", []))
            return items if isinstance(items, list) else []
        except Exception:
            pass

    args = json.dumps({"query": query, "num": num, "recency_days": recency_days})
    cmd = ["z-ai", "function", "-n", "web_search", "-a", args, "-o", str(cache_file)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=60)
        # Be polite — back off between fresh queries to avoid rate limit
        time.sleep(3)
    except Exception as e:
        log.warning("z-ai search failed: %s", e)
        return []
    if not cache_file.exists():
        return []
    try:
        with open(cache_file) as f:
            data = json.load(f)
        items = data if isinstance(data, list) else data.get("results", data.get("data", []))
        return items if isinstance(items, list) else []
    except Exception as e:
        log.warning("z-ai parse failed: %s", e)
        return []


def hn_scan() -> List[Lead]:
    """Hit HN Algolia directly — anonymous, free."""
    import urllib.request
    leads = []
    try:
        url = "https://hn.algolia.com/api/v1/search?query=Ask+HN+Who+is+hiring&tags=story&hitsPerPage=3"
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.load(r)
        for h in data.get("hits", []):
            sid = h.get("objectID")
            if not sid:
                continue
            cmt_url = f"https://hn.algolia.com/api/v1/search?tags=comment&storyID={sid}&hitsPerPage=80"
            try:
                with urllib.request.urlopen(cmt_url, timeout=20) as r2:
                    cdata = json.load(r2)
            except Exception:
                continue
            for k in cdata.get("hits", []):
                leads.append(Lead(
                    title=(k.get("story_title") or "HN Who's Hiring comment"),
                    url=f"https://news.ycombinator.com/item?id={k.get('objectID','')}",
                    source="hackernews:who_is_hiring",
                    snippet=(k.get("comment_text") or "")[:700],
                    author=k.get("author") or "",
                    created_utc=float(k.get("created_at_i") or 0),
                ))
            time.sleep(1)
    except Exception as e:
        log.warning("HN scan failed: %s", e)
    # Also direct job-search
    try:
        url = "https://hn.algolia.com/api/v1/search_by_date?tags=story&query=freelance+remote+contract+hiring&hitsPerPage=40"
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.load(r)
        for h in data.get("hits", []):
            leads.append(Lead(
                title=h.get("title",""),
                url=h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID','')}",
                source="hackernews:search",
                snippet=(h.get("story_text") or h.get("highlight", {}).get("story_text",""))[:500],
                author=h.get("author") or "",
                created_utc=float(h.get("created_at_i") or 0),
            ))
    except Exception as e:
        log.warning("HN search failed: %s", e)
    return leads


def score(text: str, created_utc: float = 0.0) -> tuple[int, list, list]:
    for p in BL:
        if p.search(text):
            return 0, [], []
    wl_hits = sum(1 for p in WL if p.search(text))
    pay_hits = []
    for p in PAY:
        m = p.search(text)
        if m:
            pay_hits.append(m.group(0).lower())
    # Dedupe pay hits
    pay_hits = list(dict.fromkeys(pay_hits))
    budget_hits = []
    for p in WL:
        if r"\d" in p.pattern or "btc" in p.pattern.lower() or "eth" in p.pattern.lower():
            m = p.search(text)
            if m:
                budget_hits.append(m.group(0))
    s = min(wl_hits*8, 40) + min(len(pay_hits)*6, 30) + min(len(budget_hits)*5, 15)
    if created_utc:
        age_h = max(0.0, (time.time()-created_utc)/3600)
        if age_h <= 24: s += 15
        elif age_h <= 72: s += 8
        elif age_h <= 168: s += 2
        else: s -= 10
    return max(0, min(100, s)), budget_hits, pay_hits


def fetch_page_text(url: str) -> str:
    """Use z-ai page_reader to fetch the actual page text (real post body)."""
    # Reddit blocks the datacenter IP this page_reader runs from, so skip it
    # — return empty so we keep the original web_search snippet instead of
    # replacing it with Reddit's "blocked" CSS noise page.
    if "reddit.com" in url:
        return ""
    out_file = RAW_DIR / f"page_{_qhash(url)}.json"
    args = json.dumps({"url": url})
    cmd = ["z-ai", "function", "-n", "page_reader", "-a", args, "-o", str(out_file)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=45)
    except Exception as e:
        log.warning("page_reader failed for %s: %s", url, e)
        return ""
    if not out_file.exists():
        return ""
    try:
        with open(out_file) as f:
            data = json.load(f)
        # The SDK may return either {data:{html}} or {html}
        html = (data.get("data") or {}).get("html") or data.get("html") or ""
        text = data.get("data", {}).get("text") or data.get("text") or ""
        # Strip HTML to plain text
        if html and not text:
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()
        # Detect noise — Reddit/Facebook blocked pages are full of CSS variables
        noise_markers = [".theme-light", "--rem360", "<body class=\"theme-beta\"", "Whoa there, partner!"]
        if any(m in text for m in noise_markers):
            return ""
        return text[:4000]
    except Exception as e:
        log.warning("page_reader parse failed: %s", e)
        return ""


def main():
    log.info("=== LeadFinder scan-now starting ===")
    all_leads: List[Lead] = []
    seen_urls = set()

    # 1) Run all web_search queries in parallel-ish batches
    for source, q, days in QUERIES:
        log.info("query: %s (recency=%dd) -> %s", source, days, q)
        hits = zai_search(q, recency_days=days, num=20)
        for h in hits:
            url = h.get("url","")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            text = f"{h.get('name','')}\n{h.get('snippet','')}"
            sc, budget_hits, pay_hits = score(text, parse_zai_date(h.get("date","")))
            if sc < 30:
                continue
            all_leads.append(Lead(
                title=h.get("name","").strip(),
                url=url,
                source=source,
                snippet=h.get("snippet","").strip(),
                score=sc,
                created_utc=parse_zai_date(h.get("date","")),
                budget_signals=budget_hits,
                payment_signals=pay_hits,
            ))

    # 2) HN direct
    log.info("scanning Hacker News directly via Algolia...")
    for l in hn_scan():
        if l.url in seen_urls:
            continue
        seen_urls.add(l.url)
        text = f"{l.title}\n{l.snippet}"
        sc, bh, ph = score(text, l.created_utc)
        if sc < 30:
            continue
        l.score = sc
        l.budget_signals = bh
        l.payment_signals = ph
        all_leads.append(l)

    # 3) Enrich top leads with real post body via page_reader
    log.info("enriching top leads with page_reader (real post body)...")
    all_leads.sort(key=lambda x: -x.score)
    enrich_targets = [l for l in all_leads[:30] if "reddit.com" in l.url or "news.ycombinator.com" in l.url]
    for l in enrich_targets:
        body = fetch_page_text(l.url)
        if body:
            l.snippet = body[:1500]
            sc, bh, ph = score(f"{l.title}\n{l.snippet}", l.created_utc)
            # Always keep enriched score if it's higher OR comparable
            l.score = max(l.score, sc)
            l.budget_signals = list(set(l.budget_signals + bh))
            l.payment_signals = list(set(l.payment_signals + ph))
        time.sleep(0.5)

    # 4) Generate outreach drafts
    log.info("generating outreach drafts for %d leads...", len(all_leads))
    for l in all_leads:
        l.outreach_draft = gen_draft(l)

    # 4) Sort + dedupe by URL (already done) + output
    all_leads.sort(key=lambda x: (-x.score, -x.created_utc))
    log.info("final lead count: %d", len(all_leads))

    # Write deliverables
    json_path = OUT_DIR / "leads.json"
    csv_path = OUT_DIR / "leads.csv"
    md_path = OUT_DIR / "leads_digest.md"

    json_path.write_text(json.dumps([l.as_dict() for l in all_leads], indent=2, ensure_ascii=False), encoding="utf-8")
    import csv, io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["score","source","title","url","budget","payment","age_hours","snippet"])
    for l in all_leads:
        w.writerow([l.score, l.source, l.title, l.url, ",".join(l.budget_signals),
                    ",".join(l.payment_signals),
                    round(max(0,(time.time()-l.created_utc)/3600),1) if l.created_utc else "",
                    (l.snippet or "")[:200].replace("\n"," ")])
    csv_path.write_text(buf.getvalue(), encoding="utf-8")

    md = [f"# LeadFinder scan digest", "",
          f"_{len(all_leads)} paid-task leads matched. Sorted by relevance score (0-100)._", "",
          "**Scanned sources:** Reddit (r/slavelabour, r/Jobs4Bitcoins, r/forhire, r/jobbit, r/DigitalCartel, r/HireaWriter, r/ProgrammingPromos, r/EmployedFreelancers, r/copywriting, r/learnpython, r/datasets, r/webdev, r/CryptoCurrency, r/ethtrader, r/freelance_forhire) + Hacker News + Bitcointalk + LaborX + Gitcoin", "",
          "> ⚠️ **Freshness note:** this scan was run from a server IP that Reddit blocks for direct `.json` access, so results are routed through a search index. Some leads may be older than ideal. For true 24/7 fresh-lead monitoring (posts < 24h old), install the `leadfinder` package on your own machine — your home IP can hit Reddit directly.", "",
          "## How to use this digest", "",
          "1. Open each URL in a browser to read the full post.", "",
          "2. If still active and a fit, copy the **Draft outreach** block and send it via Reddit PM / HN reply / platform DM.", "",
          "3. **Never automate the sending step.** Manual sending keeps you under bot-detection radar and protects your account.", "",
          "4. Negotiate payment before starting. Take half upfront for new clients. Use escrow (LaborX/CryptoTask built-in) when possible.", "",
          "5. Track which leads convert — open `leads.json` and mark a `status` field manually as you work them.", "",
          "---", ""]
    for l in all_leads:
        budget = ", ".join(l.budget_signals) if l.budget_signals else "—"
        payment = ", ".join(l.payment_signals) if l.payment_signals else "—"
        age = f"{(time.time()-l.created_utc)/3600:.1f}h ago" if l.created_utc else "—"
        md.append(f"## [{l.score}] {l.title}")
        md.append("")
        md.append(f"- **Source:** {l.source}")
        md.append(f"- **URL:** {l.url}")
        md.append(f"- **Budget signals:** {budget}")
        md.append(f"- **Payment signals:** {payment}")
        md.append(f"- **Age:** {age}")
        if l.snippet:
            md.append("")
            md.append(f"> {l.snippet[:400]}")
        md.append("")
        md.append("**Draft outreach (copy & paste manually — do NOT automate sending):**")
        md.append("")
        md.append("```")
        md.append(l.outreach_draft)
        md.append("```")
        md.append("")
        md.append("---")
        md.append("")
    md_path.write_text("\n".join(md), encoding="utf-8")

    log.info("digest -> %s", md_path)
    log.info("json -> %s", json_path)
    log.info("csv -> %s", csv_path)
    # Print top 25 to stdout
    print("\n=== TOP LEADS ===")
    for l in all_leads[:25]:
        print(f"[{l.score:3d}] {l.source:30s} {l.title[:70]}")
        print(f"     {l.url}")


def gen_draft(l: Lead) -> str:
    title = l.title.strip() or "your task"
    snip = (l.snippet or "").strip().replace("\n"," ")[:120]
    if l.source.startswith("reddit"):
        greet = "Hey — saw your Reddit post"
    elif l.source.startswith("hackernews"):
        greet = "Hi — saw your HN comment"
    elif "bitcointalk" in l.source:
        greet = "Hi — saw your Bitcointalk bounty"
    elif l.source == "laborx":
        greet = "Hi — saw your LaborX listing"
    elif l.source == "gitcoin":
        greet = "Hey — saw your Gitcoin bounty"
    else:
        greet = "Hi"
    msg = f"{greet} (\"{title[:80]}\"). "
    if snip:
        msg += f"You wrote: \"{snip}...\" — I can do this. "
    else:
        msg += "I can take this on. "
    msg += "I've done similar work recently — happy to share a quick sample or do a 10-min proof-of-concept before any commitment. "
    if l.payment_signals:
        msg += f"OK to be paid in {', '.join(l.payment_signals[:2])}. "
    else:
        msg += "Open to crypto (BTC/ETH/USDT) or PayPal — your call. "
    msg += "What's your budget + timeline? Can start today."
    words = msg.split()
    if len(words) > 80:
        msg = " ".join(words[:80]) + "..."
    return msg


if __name__ == "__main__":
    main()
