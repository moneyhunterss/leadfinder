"""Tier classification — re-export from models."""
from models import classify_tier

def classify(budget_signals: list[str]) -> str:
    return classify_tier(budget_signals)
