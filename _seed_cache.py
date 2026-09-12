"""Pre-populate the leadfinder cache: copy the earlier batch result files
(those have descriptive names like r_slavelabour.json) to the new md5-hash
naming convention so scan_now.py can reuse them."""
import json, hashlib, os, shutil
from pathlib import Path

RAW = Path("/home/z/my-project/research/raw")

# Map of original search query -> original filename (from earlier batch runs)
# These are the queries I ran earlier with their cached outputs.
QUERY_TO_FILE = {
    'site:reddit.com r/slavelabour task pay': 'r_slavelabour.json',
    'site:reddit.com r/slavelabour "task" "paid"': 'r_slavelabour_24h.json',
    'site:reddit.com r/Jobs4Bitcoins hire task': 'r_jobs4bitcoins.json',
    'site:reddit.com r/DigitalCartel task crypto pay': 'r_digitalcartel.json',
    'site:reddit.com r/forhire hiring freelancer': 'r_forhire.json',
    'site:reddit.com r/jobbit hire pay': 'r_jobbit.json',
    'site:reddit.com r/HireaWriter pay article blog': 'r_hireawriter.json',
    'site:reddit.com r/ProgrammingPromos hire dev build': 'r_programmingpromos.json',
    'site:reddit.com r/EmployedFreelancers hire contract': 'r_employedfreelancers.json',
    'site:reddit.com r/copywriting pay hire writer': 'r_copywriting.json',
    'site:reddit.com r/learnpython pay someone script build task': 'r_learnpython.json',
    'site:reddit.com r/datasets hire pay data scraping': 'r_datasets.json',
    'site:reddit.com r/webdev hire freelance pay build': 'r_webdev.json',
    'freelance gig paid crypto btc eth usdt immediately start': 'generic_crypto_gigs.json',
    'laborx.com crypto freelance task posted today': 'laborx.json',
    'gitcoin bounties open 2025 claim ETH reward': 'gitcoin.json',
    'Ask HN Who is hiring 2026 remote contract freelance': 'hn_whoshiring.json',
    'bitcointalk bounty paid task altcoin 2025': 'bitcointalk_bounties.json',
    'site:reddit.com r/forhire "[hiring]" task pay': 'r_forhire_hiring.json',
    'site:reddit.com/r/freelance_forhire hiring pay': 'r_freelance_forhire.json',
    'site:reddit.com/r/CryptoCurrency bounty task paid': 'r_cryptocurrency.json',
    'site:reddit.com/r/ethtrader bounty paid': 'r_ethtrader.json',
    'site:reddit.com r/slavelabour "[task]" -offer 2025': 'r_slavelabour_tasks.json',
    'site:reddit.com r/slavelabour "[offer]" will pay': 'r_slavelabour_offers.json',
    '"paid in crypto" task freelance looking for developer 2025': 'paid_in_crypto.json',
    'site:reddit.com r/forhire "[hiring]" freelance developer pay 2025': 'r_forhire_hiring_real.json',
    'site:reddit.com r/Jobs4Bitcoins "[task]" -meta': 'r_jobs4bitcoins_tasks.json',
    'site:reddit.com r/slavelabour "task" "paid"': 'r_slavelabour_paid.json',
}

copied = 0
for q, fname in QUERY_TO_FILE.items():
    src = RAW / fname
    if not src.exists():
        print(f"MISSING: {fname}")
        continue
    h = hashlib.md5(q.encode("utf-8")).hexdigest()
    dst = RAW / f"q_{h}.json"
    if dst.exists():
        continue
    shutil.copy2(src, dst)
    copied += 1
print(f"copied {copied} cache files")
