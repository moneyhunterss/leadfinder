"""Anonymity layer: Tor SOCKS5, proxy rotation, User-Agent rotation."""
from __future__ import annotations
import random
import os
from typing import Optional

USER_AGENTS = [
    # Real-looking desktop browsers — Reddit blocks empty/bot UAs
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]


def random_ua() -> str:
    return random.choice(USER_AGENTS)


def build_proxies(mode: str, tor_socks: str, proxy_url: Optional[str] = None) -> Optional[dict]:
    """Build a requests `proxies` dict for the chosen anonymity mode."""
    if mode == "tor" and tor_socks:
        return {"http": tor_socks, "https": tor_socks}
    if mode == "proxy" and proxy_url:
        return {"http": proxy_url, "https": proxy_url}
    return None  # direct


def session_for(mode: str, tor_socks: str, proxy_url: Optional[str] = None):
    """Return a configured requests.Session."""
    import requests
    s = requests.Session()
    s.headers.update({
        "User-Agent": random_ua(),
        "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    proxies = build_proxies(mode, tor_socks, proxy_url)
    if proxies:
        s.proxies.update(proxies)
    return s


def is_tor_available(tor_socks: str = "socks5://127.0.0.1:9050") -> bool:
    """Check whether a local Tor SOCKS port is reachable."""
    import socket
    try:
        host, _, port = tor_socks.partition(":").__iter__().__next__().replace("socks5://","").rpartition(":")  # crude parse
    except Exception:
        return False
    # simpler parse
    try:
        addr = tor_socks.replace("socks5://", "").replace("socks5h://", "")
        h, p = addr.rsplit(":", 1)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)
        s.connect((h, int(p)))
        s.close()
        return True
    except Exception:
        return False
