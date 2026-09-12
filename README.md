# LeadFinder — free / anonymous / 24-7 lead scanner + Telegram bot

A Python CLI + interactive Telegram bot that scans Reddit RSS, Hacker News,
Bitcointalk, and Web3 bounty platforms for **paid task/gig/job leads** you can
fulfill for crypto or fiat. No login, no API keys (for core path). Strict
quality gates kill garbage — only real `[HIRING]` / `[Task]` posts with payment
signals survive.

## 🚀 Quick start

### Option A — Local (interactive bot + scanner)

```bash
# 1. Clone your repo
git clone https://github.com/YOUR_USERNAME/leadfinder.git
cd leadfinder/leadfinder

# 2. Install deps
pip install -r requirements.txt

# 3. Get a Telegram bot token from @BotFather, then:
export TELEGRAM_BOT_TOKEN="123456:ABC..."
python bot.py

# 4. In Telegram, message your bot:
#    /start  -> it shows your chat_id (save this)
#    /scan   -> runs a fresh scan now
#    /leads  -> top 10 from last scan
#    /stats  -> counts by source
```

### Option B — GitHub Actions (24/7 cron, no server)

1. Push this folder to a GitHub repo.
2. Create bot via [@BotFather](https://t.me/BotFather) → get token.
3. Message your bot `/start` — it replies with your chat ID.
4. Add repo secrets: `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`.
5. Edit `.github/workflows/leadfinder-scan.yml` → set cron (default: hourly).
6. Actions tab → Run workflow → check Telegram.

**Cron schedule (edit one line in workflow YAML):**

| Schedule       | Cron              | Freshness           |
|----------------|-------------------|---------------------|
| Every 15 min   | `*/15 * * * *`    | lead < 15 min old   |
| Every 30 min   | `*/30 * * * *`    | lead < 30 min old   |
| **Every hour** | `0 * * * *`       | lead < 60 min old   |
| Every 6 hours  | `0 */6 * * *`     | lead < 6 h old      |
| Daily 9am UTC  | `0 9 * * *`       | lead < 24 h old     |

Free tier: 2,000 min/month. Hourly = ~24 min/month used.

## 🔒 Security — read this

**Never commit the bot token.** It lives only in:
- Your local env var: `export TELEGRAM_BOT_TOKEN=...`
- GitHub repo Secrets (Settings → Secrets and variables → Actions)
- Never in any file, never in chat, never in git history

If you accidentally leak a token (like sharing it in plaintext), **immediately**
revoke via @BotFather → `/revoke` and generate a new one. Any token that's
been visible in chat/screenshots/logs is compromised.

## 🤖 Bot commands

| Command   | What it does                                          |
|-----------|-------------------------------------------------------|
| `/start`  | Register + shows your chat_id (save for GitHub Secret)|
| `/help`   | List commands                                        |
| `/scan`   | Run scan_v2.py now, send top 5 fresh leads           |
| `/leads`  | Show top 10 leads from last scan                     |
| `/stats`  | Lead counts by source + score band                  |
| `/ping`   | Health check                                         |

## 📂 Project structure

```
leadfinder/
├── README.md
├── .gitignore                 ← excludes data/, .env, raw/, __pycache__
├── requirements.txt
├── config.yaml
├── bot.py                      ← interactive Telegram bot (long-polling)
├── scan_v2.py                  ← strict direct-fetch scanner (RSS + HN + Bitcointalk)
├── notify_telegram.py          ← cron notifier (diffs prev vs new leads)
├── setup_telegram.md           ← full BotFather + secrets guide
├── .github/workflows/
│   ├── leadfinder-scan.yml     ← hourly cron — scan + notify + commit state
│   └── leadfinder-bot.yml      ← long-running bot (poor-man's VPS fallback)
└── leadfinder/                ← the importable Python package
    ├── cli.py
    ├── sources/
    │   ├── reddit.py           ← .json endpoint
    │   ├── rss.py              ← 14 RSS feeds (Dev.to, HN, IndieHackers, Reddit-rss)
    │   ├── hackernews.py       ← Algolia API
    │   ├── bitcointalk.py
    │   ├── laborx.py / gitcoin.py / cryptotask.py
    ├── filters.py, store.py, exporters.py, anon.py, outreach.py
```

## 🔧 What the scanner does

1. Fetches Reddit RSS for 15 task subreddits (r/slavelabour, r/Jobs4Bitcoins, r/forhire, r/DigitalCartel, r/jobbit, r/EmployedFreelancers, r/HireaWriter, r/ProgrammingPromos, r/freelance_forhire, r/freelance, r/webdev, r/learnpython, r/datasets, r/CryptoCurrency, r/ethtrader)
2. Hits HN Algolia for hiring-flavored stories + Who's Hiring comments
3. Scrapes Bitcointalk board 73 (Bounties Altcoins)
4. Applies **strict quality gates**:
   - Age < 72h
   - Title prefix `[Hiring]/[Task]/[Paid]/[Bounty]` (drops `[for hire]/[Offer]`)
   - Body contains payment signal (USD amount, crypto, PayPal)
   - Body contains hiring signal ("looking for", "will pay", "need someone")
   - Drops questions, meta-discussion, landing pages, giveaways/scams
   - Marketing funnels (referral links) penalized -15 score
5. Generates per-lead cold-outreach draft (task-type aware: video/dev/writing/design/VA)
6. Writes `download/leads_digest.md` + `leads.json` + `leads.csv` + `data/leads.json`
7. Telegram notifier diffs against previous run — only NEW leads trigger pings

## 📋 Push to GitHub (one-time setup)

```bash
# 1. On github.com: create a new empty repo named `leadfinder` (no README, no .gitignore)

# 2. From this folder:
cd /home/z/my-project/scripts/leadfinder
git init
git add .
git commit -m "feat: LeadFinder v2 — strict direct-fetch scanner + Telegram bot"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/leadfinder.git
git push -u origin main
```

Then add repo secrets (Settings → Secrets and variables → Actions):
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID` (run `/start` in the bot to get it)

## ⚖️ Legal / ethical

- Reading public Reddit/HN/Bitcointalk pages is allowed by their ToS.
- 1 request per 3s per sub — well under Reddit's 10 QPM unauth limit.
- Outreach drafts are generated — **you send them yourself, manually**.
  Never automate sending; it violates platform ToS and gets accounts banned.
- Skip Facebook / Twitter / Telegram scraping unless you provide your own
  session cookie and understand the ToS implications.

## 🆘 Troubleshooting

- **Bot doesn't respond** → check `TELEGRAM_BOT_TOKEN` env var is set, run `python bot.py` locally and watch logs
- **GitHub Actions scan says "No changes to commit"** → that's normal when no new leads matched
- **Reddit 429 rate limit** → GitHub Actions runners have fresh IPs, won't hit this. If running locally, bump the 3s sleep in scan_v2.py
- **No leads matching** → lower `min_score` threshold in scan_v2.py (default 30)
