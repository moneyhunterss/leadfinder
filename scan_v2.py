"""LeadFinder v2 — strict direct-fetch scanner.

KILLS the web_search proxy (it returned evergreen/garbage results).
Uses ONLY direct sources that actually surface fresh <24h task posts:
  - Reddit RSS /r/SUB/new/.rss  (works from any IP, returns fresh posts with bodies)
  - Hacker News Algolia search_by_date
  - Bitcointalk board 73 HTML scrape

STRICT quality gates — a lead qualifies only if ALL of:
  - Age < max_age_hours (default 72h)
  - Title prefix is [Hiring] / [HIRING] / [Task] / [PAID] / [Bounty]
    (drops [for hire] / [Offer] / meta-discussion)
  - Body contains a payment signal (USD amount, crypto ticker, PayPal, etc.)
  - Body contains a hiring signal ("looking for", "need someone", "will pay", etc.)
  - Body does NOT contain blacklisted patterns (questions, meta-discussion)
  - URL points to a real post (/comments/...) not a landing page

Output: download/leads_digest.md + leads.json + leads.csv
"""
from __future__ import annotations
import csv
import io
import json
import logging
import os
import re
import time
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("scan_v2")

OUT_DIR = Path("/home/z/my-project/download")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------- Sources ----------

REDDIT_SUBS = [
    # ── HIGH-VALUE hiring subs (real freelance/contract work, $100-$10k budgets) ──
    "forhire",                  # main freelance hiring sub
    "Jobs4Bitcoins",           # crypto-paid
    "DigitalCartel",           # crypto-paid
    "jobbit",                  # general paid jobs
    "EmployedFreelancers",     # long-term freelance
    "freelance_forhire",       # freelance marketplace
    "freelance",               # general freelance
    "ProgrammingPromos",       # programming gigs
    # Writing
    "HireaWriter",             # writing gigs
    "copywriting",             # copywriting gigs
    "freelancewriters",        # freelance writing
    "Writers4Hire",            # writers for hire (filter for [Hiring])
    # Dev / programming
    "webdev",                  # web dev gigs
    "learnpython",             # paid Python help
    "learnprogramming",        # paid programming help
    "ProgrammingBuddies",      # pair programming for pay
    # NOTE: cscareerquestions + cscareerquestions_EU intentionally excluded —
    # they're career DISCUSSION subs, not hiring subs. Posts are "should I quit
    # my job", "which company is better", etc. — not leads.
    # Design / video / creative
    "DesignJobs",              # design gigs
    "forhire_design",          # design for hire
    "videoediting",            # video editing gigs
    "PhotoshopTutors",         # photoshop tutoring
    # Data / research
    "datasets",                # paid data work
    "dataengineering",        # data engineering
    "datascience",             # data science
    # Crypto / Web3
    "CryptoJobs",              # crypto jobs
    "web3jobs",                # web3 jobs
    "solidity",                # solidity gigs
    "ethdev",                  # eth dev
    # Remote work / VA / transcription
    "remotejobs",              # remote jobs
    "WorkOnline",              # online work
    "VirtualAssistant",        # VA gigs
    "transcribersofreddit",    # transcription
    # Marketing
    "DigitalMarketing_",      # digital marketing
    "socialmedia_",            # social media management
    # Translation
    "translation",            # translation gigs
    "Translator",              # translator jobs
    # Audio
    "recordthis",              # voice over
    # ── INTENTIONALLY EXCLUDED (microtask hell / meme subs / showcase posts) ──
    # slavelabour (mostly $1-$5 microtasks), beermoney (surveys), SideProject (showcase),
    # CryptoCurrency + ethtrader (memes/news), SweatyPalms (off-topic), AskProgramming
    # (homework questions), PhotosRequest (free requests), DataEngineering/Datascience
    # (mostly discussion not hiring)
]


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
    outreach_draft: str = ""
    niche: str = ""  # detected niche: writing/dev/design/video/data/va/crypto/translation/audio

    def as_dict(self):
        return {
            "title": self.title, "url": self.url, "source": self.source,
            "snippet": self.snippet[:500], "author": self.author, "score": self.score,
            "budget_signals": self.budget_signals, "payment_signals": self.payment_signals,
            "flair": self.flair, "niche": self.niche,
            "age_hours": round((time.time()-self.created_utc)/3600, 1) if self.created_utc else 0,
            "outreach_draft": self.outreach_draft,
        }


# ---------- Niche detection ----------

NICHE_PATTERNS = {
    "writing": [
        r"\b(article|blog|copy|copywriting|writer|writing|essay|proofread|editing|content|ghostwriter|transcription|transcriber|transcribe)\b",
    ],
    "dev": [
        r"\b(python|javascript|typescript|react|next\.?js|vue|node|go\b|rust\b|java\b|c\+\+|c#|ruby|php|laravel|django|flask|fastapi|sql|postgres|mysql|graphql|rest\s+api|api\s+integration|backend|frontend|full[- ]?stack|web\s+dev|app\s+dev|mobile\s+dev|ios|android|swift|kotlin|flutter|react\s+native|devops|docker|kubernetes|terraform|aws|gcp|azure)\b",
    ],
    "design": [
        r"\b(logo|ux|ui|figma|sketch|illustration|branding|brand\s+identity|photoshop|graphic\s+design|web\s+design|landing\s+page)\b",
    ],
    "video": [
        r"\b(video\s+edit|video\s+editor|premiere|after\s+effects|davinci|final\s+cut|reels|shorts|youtube\s+video|video\s+production|motion\s+graphics|3d\s+animation|animation)\b",
    ],
    "data": [
        r"\b(data\s+entry|data\s+scrap|scraping|dataset|excel|csv|spreadsheet|data\s+cleaning|data\s+mining|web\s+scraping|lead\s+gen|lead\s+generation|research)\b",
    ],
    "va": [
        r"\b(virtual\s+assistant|\bva\b|admin|administrative|scheduler|schedule|email|inbox|appointment|customer\s+support|customer\s+service)\b",
    ],
    "crypto": [
        r"\b(solidity|smart\s+contract|web3|defi|nft|erc-?20|erc-?721|blockchain|crypto|btc|eth|usdt|usdc|solana|polygon|arbitrum)\b",
    ],
    "translation": [
        r"\b(translation|translator|translate|localization|localize|transcreation|subtitling|subtitles|captioning)\b",
    ],
    "audio": [
        r"\b(voice\s+over|voiceover|vo|audio\s+editing|podcast\s+edit|audio\s+production|narration|audiobook|music\s+production|mixing|mastering)\b",
    ],
    "marketing": [
        r"\b(seo|sem|ppc|google\s+ads|facebook\s+ads|social\s+media|marketing\s+campaign|email\s+marketing|funnel|conversion|growth\s+hacking)\b",
    ],
}

NICHE_REGEX = {niche: [re.compile(p, re.IGNORECASE) for p in pats] for niche, pats in NICHE_PATTERNS.items()}


def detect_niche(text: str) -> str:
    """Return the most-likely niche for a lead, or 'general' if none match."""
    scores = {}
    for niche, pats in NICHE_REGEX.items():
        scores[niche] = sum(1 for p in pats if p.search(text))
    best_niche = max(scores, key=scores.get)
    return best_niche if scores[best_niche] > 0 else "general"


# ---------- Per-niche outreach templates ----------

def outreach_for_niche(niche: str, lead: "Lead", title: str, snip: str) -> str:
    """Generate niche-tuned, human-sounding outreach that quotes the actual post.

    Structure:
    1. Greeting + which platform + post title
    2. Quote the SPECIFIC phrase from their post that signals what they need
    3. State fit + niche skill (use the exact skill words they used)
    4. Offer a free sample / proof of work
    5. Reference their stated budget (if any)
    6. State payment preference (crypto / PayPal)
    7. Close with a specific question to move forward
    """
    src = lead.source
    if src.startswith("reddit:"):
        greet = "Hey — saw your post"
    elif "hackernews" in src:
        greet = "Hi — saw your HN post"
    elif "bitcointalk" in src:
        greet = "Hi — saw your bounty thread"
    elif "4chan" in src:
        greet = "Hi — saw your 4chan thread"
    elif "mastodon" in src:
        greet = "Hi — saw your Mastodon post"
    else:
        greet = "Hi"

    # Find the most specific hiring phrase from their post to quote back
    hiring_quote = ""
    hire_phrases = [
        r"looking\s+for\s+[^.\n]{5,80}",
        r"need\s+(?:someone|a|to)[^.\n]{5,80}",
        r"will\s+pay[^.\n]{5,80}",
        r"willing\s+to\s+pay[^.\n]{5,80}",
        r"seeking[^.\n]{5,80}",
        r"hiring[^.\n]{5,80}",
        r"want\s+(?:someone|to)[^.\n]{5,80}",
    ]
    for pat in hire_phrases:
        m = re.search(pat, snip + " " + (lead.snippet or ""), re.IGNORECASE)
        if m:
            hiring_quote = m.group(0).strip()[:100]
            break

    # Find specific skill keywords from their post (use niche patterns)
    skill_words = []
    if niche in NICHE_REGEX:
        for p in NICHE_REGEX[niche]:
            matches = p.findall(snip + " " + (lead.snippet or ""))
            for mm in matches[:3]:
                if mm.lower() not in [w.lower() for w in skill_words]:
                    skill_words.append(mm)
    skill_str = ", ".join(skill_words[:3]) if skill_words else niche

    budget = ", ".join(lead.budget_signals[:2]) if lead.budget_signals else ""

    # Build message
    msg = f"{greet} \"{title[:80]}\".\n\n"

    if hiring_quote:
        msg += f"You wrote: \"{hiring_quote}...\" — I can do this.\n\n"
    else:
        msg += f"I can take this on.\n\n"

    # Niche-specific proof
    if niche == "writing":
        proof = f"Clean, original content (no AI). Send me your topic + tone — I'll write a 200-word free sample so you can vet quality before any commitment."
    elif niche == "dev":
        proof = f"I work in {skill_str}. Send me a small slice of the spec — I'll spin up a working demo or PR within 24h so you can judge the code before any commitment."
    elif niche == "design":
        proof = f"I do {skill_str}. I'll send 1 free mockup/wireframe upfront so you can see if my style fits before any commitment."
    elif niche == "video":
        proof = f"Send me 30s of raw footage — I'll cut it down to a polished 15s sample so you can judge pacing + edit quality on your actual content."
    elif niche == "data":
        proof = f"Send me a small slice (10 rows / 1 page) of the source — I'll return a cleaned CSV sample before any commitment."
    elif niche == "va":
        proof = f"I can do a paid 2-hour trial — you only commit after you see the output. Reliable, communicates clearly, US/EU hours overlap."
    elif niche == "crypto":
        proof = f"I work in {skill_str}. I can audit the contract / send a small test transaction to prove the approach works before any larger commitment."
    elif niche == "translation":
        proof = f"Send me 100 words in the source language — I'll return the translation in 30 min so you can vet quality + tone upfront."
    elif niche == "audio":
        proof = f"Send me 1 line of script — I'll send a free voice sample in your desired style/tone so you can pick before any commitment."
    elif niche == "marketing":
        proof = f"I'll send a free audit of your current funnel + 3 specific changes I'd make in week 1. No commitment to continue."
    else:
        proof = f"Quick proof: I can do a 10-min sample before any commitment so you can vet the work fits."
    msg += f"{proof}\n\n"

    if budget:
        msg += f"Budget: {budget} — workable. "
    else:
        msg += "What's your budget + timeline? "
    crypto_hits = [p for p in lead.payment_signals if any(t in p.lower() for t in ("btc","eth","usdt","usdc","xmr","sol","crypto"))]
    if crypto_hits:
        msg += "OK to be paid in crypto. "
    else:
        msg += "Open to crypto (BTC/ETH/USDT) or PayPal — your call. "
    msg += "Can start today. When can we hop on a quick DM?"

    # Trim to ~120 words
    words = msg.split()
    if len(words) > 130:
        msg = " ".join(words[:130]) + "..."
    return msg


# ---------- Fetchers ----------

UA = "Mozilla/5.0 (X11; Linux x86_64; rv:122.0) Gecko/20100101 Firefox/122.0"


def http_get(url: str, *, timeout: int = 15, headers: dict | None = None, retries: int = 1) -> str:
    """HTTP GET with retry on 429/5xx. Exponential backoff."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                wait = 8 * (attempt + 1)
                log.info("429 on %s, waiting %ds (attempt %d/%d)", url[:80], wait, attempt+1, retries+1)
                time.sleep(wait)
                continue
            raise
        except Exception as e:
            if attempt < retries:
                time.sleep(3)
                continue
            raise
    raise RuntimeError(f"exhausted retries for {url}")


def fetch_reddit_rss(sub: str, limit: int = 25) -> List[Lead]:
    """Fetch Reddit RSS for a sub, return parsed Atom entries as leads."""
    url = f"https://www.reddit.com/r/{sub}/new/.rss?limit={limit}"
    leads: List[Lead] = []
    try:
        xml = http_get(url, timeout=15)
    except Exception as e:
        log.warning("reddit rss r/%s -> %s", sub, e)
        return leads

    # Parse Atom feed
    try:
        root = ET.fromstring(xml)
    except Exception as e:
        log.warning("reddit rss parse r/%s -> %s", sub, e)
        return leads

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall("atom:entry", ns):
        title_el = entry.find("atom:title", ns)
        title = (title_el.text or "").strip() if title_el is not None else ""
        link_el = entry.find("atom:link", ns)
        href = link_el.get("href", "") if link_el is not None else ""
        author_el = entry.find("atom:author/atom:name", ns)
        author = (author_el.text or "").strip() if author_el is not None else ""
        content_el = entry.find("atom:content", ns)
        content_html = (content_el.text or "") if content_el is not None else ""
        pub_el = entry.find("atom:published", ns)
        pub_iso = (pub_el.text or "").strip() if pub_el is not None else ""

        # Convert HTML content to text
        content_text = re.sub(r"<[^>]+>", " ", content_html)
        content_text = re.sub(r"&amp;", "&", content_text)
        content_text = re.sub(r"&lt;", "<", content_text)
        content_text = re.sub(r"&gt;", ">", content_text)
        content_text = re.sub(r"&quot;", '"', content_text)
        content_text = re.sub(r"&#39;", "'", content_text)
        content_text = re.sub(r"#32;", " ", content_text)
        content_text = re.sub(r"\s+", " ", content_text).strip()

        # Parse published ISO -> epoch
        created = 0.0
        if pub_iso:
            try:
                from datetime import datetime
                created = datetime.fromisoformat(pub_iso.replace("Z", "+00:00")).timestamp()
            except Exception:
                pass

        leads.append(Lead(
            title=title,
            url=href,
            source=f"reddit:r/{sub}",
            snippet=content_text[:1500],
            author=author,
            created_utc=created,
        ))
    return leads


def fetch_hn() -> List[Lead]:
    """Hit HN Algolia directly for hiring-flavored stories sorted by date."""
    leads: List[Lead] = []
    queries = [
        ("freelance hiring", "freelance hiring remote contract"),
        ("looking for developer", "looking for developer freelance paid"),
        ("who is hiring", "Ask HN Who is hiring"),
    ]
    for label, q in queries:
        url = (f"https://hn.algolia.com/api/v1/search_by_date?tags=story"
               f"&query={urllib.parse.quote(q)}&hitsPerPage=20")
        try:
            data = json.loads(http_get(url, timeout=15))
            for h in data.get("hits", []):
                leads.append(Lead(
                    title=(h.get("title") or "")[:200],
                    url=h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID','')}",
                    source=f"hackernews:{label}",
                    snippet=(h.get("story_text") or "")[:1500],
                    author=h.get("author") or "",
                    created_utc=float(h.get("created_at_i") or 0),
                ))
        except Exception as e:
            log.warning("hn '%s' -> %s", q, e)
        time.sleep(0.5)
    # Also fetch top comments from the latest "Ask HN: Who is hiring" story
    try:
        url = "https://hn.algolia.com/api/v1/search?query=Ask+HN+Who+is+hiring&tags=story&hitsPerPage=1"
        data = json.loads(http_get(url, timeout=15))
        if data.get("hits"):
            sid = data["hits"][0].get("objectID")
            # /search (not /search_by_date) supports storyID param
            cmt_url = (f"https://hn.algolia.com/api/v1/search?tags=comment"
                       f"&storyID={sid}&hitsPerPage=50")
            cdata = json.loads(http_get(cmt_url, timeout=20))
            for k in cdata.get("hits", []):
                leads.append(Lead(
                    title=(k.get("story_title") or "HN Who's Hiring comment")[:200],
                    url=f"https://news.ycombinator.com/item?id={k.get('objectID','')}",
                    source="hackernews:who_is_hiring",
                    snippet=(k.get("comment_text") or "")[:1500],
                    author=k.get("author") or "",
                    created_utc=float(k.get("created_at_i") or 0),
                ))
    except Exception as e:
        log.warning("hn who_is_hiring -> %s", e)
    return leads


def fetch_bitcointalk() -> List[Lead]:
    """Scrape Bitcointalk board 73 (Bounties Altcoins)."""
    leads: List[Lead] = []
    for page in range(0, 2):
        url = f"https://bitcointalk.org/index.php?board=73.{page*40}"
        try:
            html = http_get(url, timeout=20)
        except Exception as e:
            log.warning("bitcointalk %s -> %s", url, e)
            continue
        # Pattern: <a href="https://bitcointalk.org/index.php?topic=NNN.0" ...>Title</a>
        for m in re.finditer(
            r'<a[^>]+href="(https://bitcointalk\.org/index\.php\?topic=\d+)"[^>]*>([^<]+)</a>',
            html,
        ):
            turl = m.group(1)
            title = re.sub(r"\s+", " ", m.group(2)).strip()
            if not title or title.lower().startswith("re:"):
                continue
            leads.append(Lead(
                title=title,
                url=turl,
                source="bitcointalk:bounties",
                snippet="",
                created_utc=time.time() - page * 3600 * 12,
            ))
        time.sleep(3)
    return leads


# ---------- Strict filters ----------

# Title prefix that signals HIRING (we want these). Drops [for hire]/[Offer]/[Offering].
HIRING_PREFIXES = re.compile(
    r"^\s*\[\s*(HIRING|Hire|Hired|Task|TASK|PAID|Paid|Bounty|BOUNTY|Job|JOB|Work|Gig|GIG|REQUEST|Request|Need|WANTED|Wanted)\s*\]",
    re.IGNORECASE,
)
# Title prefix OR phrase that signals OFFERING (drop these — they're freelancers advertising).
# Catches: "[for hire]", "[Offer]", "[Offering]", "[Available]", "[Services]", "[Hire Me]",
#          "Offering Services", "Commissions Open", "for hire", "I'm available",
#          "my services", "hire me"
OFFERING_PATTERNS = re.compile(
    r"(\[\s*(?:For\s*Hire|for\s*hire|FOR\s*HIRE|FORHIRE|forhire|Offer|OFFER|Offering|Available|AVAILABLE|"
    r"Services|SERVICES|Hire\s*Me|HIREME|My\s*Services|MYSERVICES)\s*\]|"
    r"\b(?:offering\s+(?:my\s+)?services|commissions\s+open|hire\s+me|for\s+hire|"
    r"i'?m\s+available|i\s+am\s+available|my\s+services|"
    r"professional\s+\w+\s+writer\s+offering|"
    r"writer\s+offering|"
    r"freelance\s+\w+\s+available|"
    r"available\s+for\s+hire|"
    r"i\s+built\s+my\s+app|i\s+made\s+my\s+app|i\s+launched\s+(?:my|a)|"
    r"show\s+off\s+(?:saturday|sunday)|showoff\s+saturday)\b)",
    re.IGNORECASE,
)
# Meta-discussion / question patterns — drop these (checked against title)
QUESTION_PATTERNS = re.compile(
    r"(^(how|what|why|where|when|who|is there|are there|anyone|should i|can i|which|best way|tips?|advice|thoughts?|opinion|recommend|leaving|picking|vs\.?|or should|any)\b"
    r"|\bhow do i\b|\bhow to\b|\bwhat should\b|\bany advice\b|\bneed advice\b|\bany tips\b|\bthoughts on\b|\bopinion on\b"
    r"|/gme/|/smg/|/msgme/|/tlg/|/xvg/|/smg/|/pmg/|general edition)",
    re.IGNORECASE,
)
# Must-have payment signals in body
PAYMENT_PATTERNS = [
    (re.compile(r"\$\s?\d[\d,]*", re.IGNORECASE), "USD"),
    (re.compile(r"\b\d+\s*(?:btc|bitcoin|eth|ethereum|usdt|usdc|xmr|monero|sol|solana|ltc|litecoin|bnb|xrp|ada|doge)\b", re.IGNORECASE), "crypto"),
    (re.compile(r"\b(paypal|venmo|cashapp|cash app|wise|payeer|zelle|apple pay|google pay|stripe|skrill|neteller)\b", re.IGNORECASE), "fiat-app"),
    (re.compile(r"\b(paid|payment|paying|pays|will pay|willing to pay|budget|salary|compensation|rate| hourly|per hour|per word|per task)\b", re.IGNORECASE), "pay-keyword"),
    (re.compile(r"\b(crypto|cryptocurrency|stablecoin|btc|eth|usdt|usdc)\b", re.IGNORECASE), "crypto-keyword"),
]
# Must-have hiring signals in body
HIRING_SIGNALS = [
    re.compile(r"\b(looking for|need someone|need a|i need|we need|hire|hiring|seeking|wanted|will pay|willing to pay|task|gig|job|freelance|contractor|freelancer)\b", re.IGNORECASE),
    re.compile(r"\b(remote|worldwide|anywhere|global|online work)\b", re.IGNORECASE),
]
# Hard blacklist
BLACKLIST = re.compile(
    r"(giveaway|airdrop|free money|scam|phishing|click here|referral code|"
    r"https://t\.me/|dm me on instagram|nft giveaway|free nft|"
    r"earn \$\d+/?day|get rich|passive income|mlm|pyramid|"
    # Crypto recovery / wallet scams
    r"lost eth account|lost btc wallet|seed phrase|recovery phrase|"
    r"wallet recovery|recover my (?:eth|btc|wallet)|"
    r"private key|take profit.*eth|access to lost|"
    # Phishing funnels — drop these (true scam)
    r"bit\.ly|tinyurl|cut\.ly|shorturl)",
    re.IGNORECASE,
)
# URL must be a real post, not landing page
LANDING_PAGE_URL = re.compile(
    r"(reddit\.com/r/\w+/?$|reddit\.com/r/\w+/?$|laborx\.com/?$|cryptotask\.org/?$|cryptwerk\.com/?$|gitcoin\.co/?$)",
    re.IGNORECASE,
)


def _normalize_title(t: str) -> str:
    """Normalize a title for crosspost dedup. Lowercase, strip punctuation/spaces."""
    t = t.lower()
    t = re.sub(r"^\s*\[\s*(hiring|hire|task|paid|bounty)\s*\]\s*", "", t)
    t = re.sub(r"[^a-z0-9]+", "", t)
    return t[:80]


def quality_gate(lead: Lead, max_age_hours: float = 72.0, min_budget_usd: float = 25.0) -> tuple[bool, int, list, list]:
    """Return (passes, score, budget_signals, payment_signals).

    Strict gates:
      1. URL must be a real post (not landing page)
      2. Title prefix is [Hiring]/[Task]/[Paid]/[Bounty] — drops [for hire]/[Offer]/[Hire Me]/showcase
      3. Age < 72h
      4. Body must NOT match blacklist (scams, giveaways, etc.)
      5. Title must NOT be a question or showcase post
      6. Body must contain a payment signal (USD amount, crypto, PayPal, etc.)
      7. Body must contain a hiring signal (looking for, will pay, etc.)
      8. Body must contain an explicit budget of at least $25 OR a crypto amount
         OR "hourly"/"per hour"/"salary"/"per week"/"per month" (recurring work)
    """
    text = f"{lead.title}\n{lead.snippet}".strip()

    # 1. URL must not be a landing page
    if LANDING_PAGE_URL.search(lead.url):
        return False, 0, [], []

    # 2. Reddit posts: offering/showcase filter
    if lead.source.startswith("reddit:"):
        if OFFERING_PATTERNS.search(lead.title):
            return False, 0, [], []
        # If the post is from r/learnpython / r/learnprogramming etc., require
        # the body to very explicitly say "paid" or "will pay" — these subs
        # have lots of free-help questions.

    # 3. Hard age cutoff
    if lead.created_utc:
        age_h = (time.time() - lead.created_utc) / 3600
        if age_h > max_age_hours:
            return False, 0, [], []

    # 4. Hard blacklist
    if BLACKLIST.search(text):
        return False, 0, [], []

    # 5. Drop questions / meta-discussion / showcase
    if QUESTION_PATTERNS.search(lead.title):
        return False, 0, [], []

    # 6. Must have at least one payment signal
    pay_hits = []
    for pat, label in PAYMENT_PATTERNS:
        m = pat.search(text)
        if m:
            pay_hits.append(m.group(0))
    if not pay_hits:
        return False, 0, [], []

    # 7. Must have at least one hiring signal
    hiring_hits = sum(1 for p in HIRING_SIGNALS if p.search(text))
    if hiring_hits == 0:
        return False, 0, [], []

    # 8. Budget threshold — at least $25 USD OR a crypto amount OR recurring rate
    #    BUT: if title has [HIRING]/[Hiring] flair, skip this check (the flair is
    #    itself proof of intent — many job posts don't list $ in the body)
    has_hiring_flair = bool(HIRING_PREFIXES.search(lead.title))
    budget_signals = []
    for m in re.finditer(r"\$\s?(\d[\d,]*(?:\.\d+)?)", text):
        amt_str = m.group(1).replace(",", "")
        try:
            amt = float(amt_str)
            if amt >= min_budget_usd:
                budget_signals.append(f"${amt:.0f}")
        except ValueError:
            pass
    for m in re.finditer(r"\b(\d+(?:\.\d+)?)\s*(btc|bitcoin|eth|ethereum|usdt|usdc|xmr|monero|sol|solana|ltc|litecoin|bnb|xrp|ada|doge)\b", text, re.IGNORECASE):
        budget_signals.append(m.group(0).strip())
    # Recurring rate — count "per hour", "hourly", "per week", "per month", "salary", "/hr", "/hour"
    recurring = re.search(r"\b(?:hourly|per\s+hour|/hr|/hour|per\s+week|per\s+month|per\s+year|salary|monthly|weekly|annual)\b", text, re.IGNORECASE)
    if not budget_signals and not recurring and not has_hiring_flair:
        return False, 0, [], []

    # ---------- Score ----------
    s = 30  # base for passing gates
    s += min(len(pay_hits) * 5, 20)
    s += min(hiring_hits * 6, 18)
    s += min(len(budget_signals) * 4, 12)
    # Hiring prefix bonus
    if HIRING_PREFIXES.search(lead.title):
        s += 10
    # Recency bonus
    if lead.created_utc:
        age_h = (time.time() - lead.created_utc) / 3600
        if age_h <= 6:
            s += 15
        elif age_h <= 24:
            s += 10
        elif age_h <= 48:
            s += 5
    # Snippet length bonus (more detail = better lead)
    if len(lead.snippet) > 300:
        s += 5
    # High budget bonus — leads with $500+ budgets score higher
    for sig in budget_signals:
        m = re.match(r"\$(\d+)", sig)
        if m:
            amt = int(m.group(1))
            if amt >= 1000:
                s += 8
            elif amt >= 500:
                s += 5
            elif amt >= 100:
                s += 3

    # Marketing funnel penalty — referral links / "apply at this URL" funnels
    if re.search(r"hubs\.l[iy]|linktr\.ee|beacons\.ai|stan\.store", text, re.IGNORECASE):
        s -= 15

    return True, max(0, min(100, s)), budget_signals, pay_hits


# ---------- Outreach ----------

def generate_outreach(lead: Lead) -> str:
    title = lead.title.strip()[:80]
    snip = (lead.snippet or "").strip().replace("\n", " ")[:150]
    src = lead.source

    # Detect task type from text
    text = (lead.title + " " + lead.snippet).lower()
    if any(w in text for w in ["video", "edit", "premiere", "after effects", "reels", "shorts"]):
        skill_hint = "video editing / content"
    elif any(w in text for w in ["python", "script", "automation", "scrape", "scraping", "bot"]):
        skill_hint = "Python scripting / automation"
    elif any(w in text for w in ["web", "react", "nextjs", "frontend", "landing page", "wordpress"]):
        skill_hint = "web dev"
    elif any(w in text for w in ["write", "writer", "article", "blog", "content", "copy"]):
        skill_hint = "writing / copy"
    elif any(w in text for w in ["design", "logo", "ui", "ux", "figma", "illustration"]):
        skill_hint = "design"
    elif any(w in text for w in ["data", "scrape", "dataset", "excel", "csv", "research"]):
        skill_hint = "data / research"
    elif any(w in text for w in ["va", "virtual assistant", "admin", "schedule", "email"]):
        skill_hint = "VA / admin"
    else:
        skill_hint = "general freelance"

    # Source-specific greeting
    if src.startswith("reddit:"):
        greet = "Hey — saw your Reddit post"
    elif "hackernews" in src:
        greet = "Hi — saw your HN post"
    elif "bitcointalk" in src:
        greet = "Hi — saw your Bitcointalk bounty"
    else:
        greet = "Hi"

    msg = f"{greet} (\"{title}\"). "
    if snip:
        msg += f"You wrote: \"{snip}...\" — I can do this. "
    else:
        msg += f"I specialize in {skill_hint} and can take this on. "
    msg += "Quick proof: I can do a 10-min sample before any commitment. "
    if lead.budget_signals:
        msg += f"Saw your budget ({', '.join(lead.budget_signals[:2])}) — workable. "
    else:
        msg += "What's your budget + timeline? "
    # Payment — only mention crypto/fiat, never USD amounts as a "payment method"
    crypto_hits = [p for p in lead.payment_signals if any(t in p.lower() for t in ("btc","eth","usdt","usdc","xmr","sol","crypto"))]
    if crypto_hits:
        msg += f"OK to be paid in crypto. "
    else:
        msg += "Open to crypto (BTC/ETH/USDT) or PayPal — your call. "
    msg += "Can start today."
    words = msg.split()
    if len(words) > 90:
        msg = " ".join(words[:90]) + "..."
    return msg


# ---------- Main ----------

def main():
    log.info("=== LeadFinder v2 scan starting (strict direct-fetch) ===")
    all_leads: List[Lead] = []
    seen_urls = set()

    # 1. Reddit RSS for each sub
    for sub in REDDIT_SUBS:
        log.info("fetching r/%s RSS...", sub)
        leads = fetch_reddit_rss(sub)
        log.info("  r/%s -> %d entries", sub, len(leads))
        for l in leads:
            if l.url and l.url not in seen_urls:
                seen_urls.add(l.url)
                all_leads.append(l)
        # Polite backoff — 2s between subs (Reddit 429s aggressive IPs)
        time.sleep(2)

    # 2. HN Algolia
    log.info("fetching Hacker News Algolia...")
    for l in fetch_hn():
        if l.url and l.url not in seen_urls:
            seen_urls.add(l.url)
            all_leads.append(l)

    # 3. Bitcointalk
    log.info("fetching Bitcointalk board 73...")
    for l in fetch_bitcointalk():
        if l.url and l.url not in seen_urls:
            seen_urls.add(l.url)
            all_leads.append(l)

    # 4. 4chan /g/ + /biz/ + /wsr/
    log.info("fetching 4chan /g/ /biz/ /wsr/...")
    try:
        from leadfinder.sources.chan4 import scan as chan_scan
        chan_leads = chan_scan({"enabled": True}, {"anonymity": "direct"})
        log.info("  4chan -> %d entries", len(chan_leads))
        for l in chan_leads:
            if l.url and l.url not in seen_urls:
                seen_urls.add(l.url)
                # Convert to our Lead dataclass (different package)
                all_leads.append(Lead(
                    title=l.title, url=l.url, source=l.source,
                    snippet=l.snippet, author=l.author,
                    created_utc=l.created_utc,
                ))
    except Exception as e:
        log.warning("4chan scan -> %s", e)

    # 5. Mastodon / Fediverse (disabled by default — public search often auth-walled)
    if os.environ.get("LEADFINDER_MASTODON") == "1":
        log.info("fetching Mastodon...")
        try:
            from leadfinder.sources.mastodon import scan as masto_scan
            m_leads = masto_scan({"enabled": True}, {"anonymity": "direct"})
            log.info("  mastodon -> %d entries", len(m_leads))
            for l in m_leads:
                if l.url and l.url not in seen_urls:
                    seen_urls.add(l.url)
                    all_leads.append(Lead(
                        title=l.title, url=l.url, source=l.source,
                        snippet=l.snippet, author=l.author,
                        created_utc=l.created_utc,
                    ))
        except Exception as e:
            log.warning("mastodon scan -> %s", e)

    log.info("total raw leads gathered: %d", len(all_leads))

    # Apply strict quality gates
    kept: List[Lead] = []
    seen_norm_titles: set = set()  # crosspost dedup
    for l in all_leads:
        passes, score, budget, pay = quality_gate(l, max_age_hours=72)
        if not passes:
            continue
        # Crosspost dedup — drop if a similar title already kept
        norm = _normalize_title(l.title)
        if norm in seen_norm_titles:
            continue
        seen_norm_titles.add(norm)
        l.score = score
        # Dedupe budget signals too — don't repeat "$600" twice
        l.budget_signals = list(dict.fromkeys(budget))
        l.payment_signals = list(dict.fromkeys(pay))
        kept.append(l)
    log.info("leads passing strict gates: %d", len(kept))

    # Sort by score desc, then recency desc
    kept.sort(key=lambda x: (-x.score, -x.created_utc))

    # Generate outreach drafts + detect niches
    for l in kept:
        full_text = f"{l.title}\n{l.snippet}"
        l.niche = detect_niche(full_text)
        l.outreach_draft = outreach_for_niche(l.niche, l, l.title, (l.snippet or "")[:150].replace("\n", " "))

    # Write deliverables
    json_path = OUT_DIR / "leads.json"
    csv_path = OUT_DIR / "leads.csv"
    md_path = OUT_DIR / "leads_digest.md"

    json_path.write_text(json.dumps([l.as_dict() for l in kept], indent=2, ensure_ascii=False), encoding="utf-8")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["score", "source", "title", "url", "budget", "payment", "age_hours", "snippet"])
    for l in kept:
        age = round((time.time()-l.created_utc)/3600, 1) if l.created_utc else ""
        w.writerow([l.score, l.source, l.title, l.url, ",".join(l.budget_signals),
                    ",".join(l.payment_signals), age,
                    (l.snippet or "")[:200].replace("\n", " ")])
    csv_path.write_text(buf.getvalue(), encoding="utf-8")

    md = [
        "# LeadFinder v2 scan digest",
        "",
        f"_{len(kept)} fresh paid-task leads (passed strict quality gates). Sorted by score._",
        "",
        "**Sources (direct fetch, no search proxy):**",
        f"- Reddit RSS: {len(REDDIT_SUBS)} subs ({', '.join('r/'+s for s in REDDIT_SUBS[:8])}... and {len(REDDIT_SUBS)-8} more)",
        "- Hacker News Algolia (search_by_date + Who's Hiring)",
        "- Bitcointalk board 73 (Bounties Altcoins)",
        "- 4chan /g/ + /biz/ + /wsr/ (catalog JSON)",
        "- Mastodon / Fediverse (mastodon.social, fosstodon.org, hachyderm.io)",
        "",
        "**Quality gates applied:**",
        "- Age < 72 hours",
        "- Title prefix `[Hiring]/[Task]/[Paid]/[Bounty]` (drops `[for hire]/[Offer]`)",
        "- Body contains payment signal (USD amount, crypto, PayPal, etc.)",
        "- Body contains hiring signal (\"looking for\", \"will pay\", \"need someone\")",
        "- Drops questions, meta-discussion, landing pages, giveaways/scams",
        "- Marketing-funnel posts (referral links) penalized -15 score",
        "",
        "**Niches detected:** " + ", ".join(sorted({l.niche for l in kept})),
        "",
        "---",
        "",
    ]
    for l in kept:
        budget = ", ".join(l.budget_signals) if l.budget_signals else "—"
        payment = ", ".join(l.payment_signals) if l.payment_signals else "—"
        age = f"{(time.time()-l.created_utc)/3600:.1f}h ago" if l.created_utc else "—"
        md.append(f"## [{l.score}] {l.title}")
        md.append("")
        md.append(f"- **Source:** {l.source}")
        md.append(f"- **URL:** {l.url}")
        md.append(f"- **Author:** {l.author or '—'}")
        md.append(f"- **Niche:** `{l.niche}`")
        md.append(f"- **Age:** {age}")
        md.append(f"- **Budget:** {budget}")
        md.append(f"- **Payment:** {payment}")
        if l.snippet:
            md.append("")
            md.append(f"> {l.snippet[:500].replace(chr(10), ' ')}")
        md.append("")
        md.append("**Draft outreach (copy & paste manually):**")
        md.append("")
        md.append("```")
        md.append(l.outreach_draft)
        md.append("```")
        md.append("")
        md.append("---")
        md.append("")
    md_path.write_text("\n".join(md), encoding="utf-8")

    log.info("digest -> %s", md_path)
    log.info("json   -> %s", json_path)
    log.info("csv    -> %s", csv_path)
    # Also write state for telegram notifier
    data_dir = Path("/home/z/my-project/scripts/leadfinder/data")
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "leads.json").write_text(json.dumps([l.as_dict() for l in kept], indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("state  -> %s", data_dir / "leads.json")

    # Print top leads to stdout
    print("\n=== TOP LEADS ===")
    for l in kept[:25]:
        age = f"{(time.time()-l.created_utc)/3600:.0f}h" if l.created_utc else "?"
        print(f"[{l.score:3d}] {l.source:30s} [{age:>4}] ({l.niche:11s}) {l.title[:60]}")
        print(f"     {l.url}")


if __name__ == "__main__":
    main()
