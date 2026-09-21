"""Tests — quality gates, niche, tier, pipeline. 20 tests."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from models import Lead, classify_tier
from filters.gates import quality_gate
from classifiers.niche import detect_niche


# ─── Tier ───
def test_tier_micro(): assert classify_tier(["$10"]) == "micro"
def test_tier_standard(): assert classify_tier(["$50"]) == "standard"
def test_tier_standard_high(): assert classify_tier(["$200"]) == "standard"
def test_tier_pro(): assert classify_tier(["$500"]) == "pro"
def test_tier_elite(): assert classify_tier(["$5000"]) == "elite"
def test_tier_elite_btc(): assert classify_tier(["1 btc"]) == "elite"
def test_tier_empty(): assert classify_tier([]) == "unspecified"

# ─── Gates ───
def test_hiring_passes():
    l = Lead(title="[Hiring] Designer", url="https://reddit.com/r/forhire/comments/abc/test",
             source="reddit:r/forhire", snippet="Looking for someone to design. Will pay $800.",
             created_utc=time.time() - 3600)
    p, s, b, _ = quality_gate(l)
    assert p and s >= 50

def test_offering_dropped():
    l = Lead(title="[For Hire] Developer", url="https://reddit.com/r/forhire/comments/xyz/test",
             source="reddit:r/forhire", snippet="I'm available. $50/hr.")
    assert not quality_gate(l)[0]

def test_question_dropped():
    l = Lead(title="How do I start freelancing?", url="https://reddit.com/r/freelance/comments/q/test",
             source="reddit:r/freelance", snippet="Any advice? Will pay.")
    assert not quality_gate(l)[0]

def test_scam_dropped():
    l = Lead(title="[Task] Lost ETH recovery", url="https://reddit.com/r/crypto/comments/s/test",
             source="reddit:r/crypto", snippet="Seed phrase not working. $1000.")
    assert not quality_gate(l)[0]

def test_old_dropped():
    l = Lead(title="[Hiring] Dev", url="https://reddit.com/r/forhire/comments/old/test",
             source="reddit:r/forhire", snippet="Looking for dev. $500.",
             created_utc=time.time() - 200 * 3600)
    assert not quality_gate(l, max_age_hours=72)[0]

def test_flair_bypass():
    l = Lead(title="[HIRING] DevOps", url="https://reddit.com/r/remote/comments/flair/test",
             source="reddit:r/remote", snippet="Remote, long-term.",
             created_utc=time.time() - 3600)
    assert quality_gate(l)[0]

def test_landing_dropped():
    l = Lead(title="Freelance jobs", url="https://reddit.com/r/forhire",
             source="reddit:r/forhire", snippet="Will pay $500.")
    assert not quality_gate(l)[0]

def test_no_payment_dropped():
    l = Lead(title="Looking for developer", url="https://reddit.com/r/forhire/comments/nb/test",
             source="reddit:r/forhire", snippet="Need someone to build a website.")
    assert not quality_gate(l)[0]

def test_comment_boost():
    l1 = Lead(title="[Task] Build app", url="https://reddit.com/r/slavelabour/comments/a/test",
              source="reddit:r/slavelabour", snippet="Need app built. $50.", created_utc=time.time()-3600, comment_count=0)
    l2 = Lead(title="[Task] Build app", url="https://reddit.com/r/slavelabour/comments/b/test",
              source="reddit:r/slavelabour", snippet="Need app built. $50.", created_utc=time.time()-3600, comment_count=10)
    s1 = quality_gate(l1)[1]
    s2 = quality_gate(l2)[1]
    assert s2 > s1  # More comments = higher score

def test_low_karma_penalty():
    l1 = Lead(title="[Task] Build app", url="https://reddit.com/r/slavelabour/comments/k1/test",
              source="reddit:r/slavelabour", snippet="Need app. $50.", created_utc=time.time()-3600, karma=500)
    l2 = Lead(title="[Task] Build app", url="https://reddit.com/r/slavelabour/comments/k2/test",
              source="reddit:r/slavelabour", snippet="Need app. $50.", created_utc=time.time()-3600, karma=50)
    s1 = quality_gate(l1)[1]
    s2 = quality_gate(l2)[1]
    assert s1 > s2  # Low karma = lower score

def test_referral_penalty():
    l = Lead(title="[Hiring] Test", url="https://reddit.com/r/forhire/comments/ref/test",
             source="reddit:r/forhire", snippet="Looking for someone. $100. Apply: hubs.ly/Q123",
             created_utc=time.time()-3600)
    p, s, _, _ = quality_gate(l)
    assert p and s < 60  # Passes but penalized

# ─── Niche ───
def test_niche_dev(): assert detect_niche("need a Python script") == "dev"
def test_niche_design(): assert detect_niche("logo designer for brand") == "design"
def test_niche_video(): assert detect_niche("video editor for youtube") == "video"
def test_niche_motion(): assert detect_niche("motion graphics designer") == "motion"
def test_niche_writing(): assert detect_niche("article writer needed") == "writing"
def test_niche_va(): assert detect_niche("virtual assistant for admin") == "va"
def test_niche_general(): assert detect_niche("random text here") == "general"
