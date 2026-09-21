"""Config loader — YAML + env vars. Zero hardcoded values."""
from __future__ import annotations
import os
from pathlib import Path
import yaml


class Config:
    def __init__(self):
        p = Path(__file__).resolve().parents[2] / "config" / "config.yaml"
        if not p.exists():
            p = Path(os.environ.get("LEADFINDER_CONFIG", "config/config.yaml"))
        self._data = {}
        if p.exists():
            with open(p) as f:
                self._data = yaml.safe_load(f) or {}

    def get(self, *keys, default=None):
        v = self._data
        for k in keys:
            if isinstance(v, dict): v = v.get(k)
            else: return default
            if v is None: return default
        return v

    @property
    def scanner(self): return self._data.get("scanner", {})
    @property
    def reddit(self): return self._data.get("reddit", {})
    @property
    def hn(self): return self._data.get("hn", {})
    @property
    def bitcointalk(self): return self._data.get("bitcointalk", {})
    @property
    def notifier(self): return self._data.get("notifier", {})
    @property
    def bot_cfg(self): return self._data.get("bot", {})
    @property
    def pipeline_cfg(self): return self._data.get("pipeline", {})
    @property
    def portfolio(self): return self._data.get("portfolio", {})
    @property
    def turso(self): return self._data.get("turso", {})
    @property
    def reddit_oauth_enabled(self):
        r = self.reddit
        return bool(r.get("client_id") and r.get("client_secret"))
    @property
    def turso_enabled(self):
        return bool(self.turso.get("url") and self.turso.get("auth_token"))
    @property
    def telegram_token(self): return os.environ.get("TELEGRAM_BOT_TOKEN", "")
    @property
    def telegram_chat_id(self): return os.environ.get("TELEGRAM_CHAT_ID", "")
    @property
    def reddit_client_id(self): return os.environ.get("REDDIT_CLIENT_ID", self.reddit.get("client_id", ""))
    @property
    def reddit_client_secret(self): return os.environ.get("REDDIT_CLIENT_SECRET", self.reddit.get("client_secret", ""))
    @property
    def reddit_username(self): return os.environ.get("REDDIT_USERNAME", self.reddit.get("username", ""))
    @property
    def reddit_password(self): return os.environ.get("REDDIT_PASSWORD", self.reddit.get("password", ""))
