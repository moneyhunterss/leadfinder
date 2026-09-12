"""Exporters: pretty CLI table, Markdown digest, JSON, CSV."""
from __future__ import annotations
import csv
import json
from typing import List
from .filters import Lead


def to_json(leads: List[Lead]) -> str:
    return json.dumps([l.as_dict() for l in leads], indent=2, ensure_ascii=False)


def to_csv(leads: List[Lead]) -> str:
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["score", "source", "title", "url", "budget", "payment", "age_hours", "flair", "snippet"])
    for l in leads:
        w.writerow([
            l.score, l.source, l.title, l.url,
            ",".join(l.budget_signals),
            ",".join(l.payment_signals),
            round(l.age_hours, 1),
            l.flair,
            (l.snippet or "")[:200].replace("\n", " "),
        ])
    return buf.getvalue()


def to_markdown(leads: List[Lead], *, title: str = "LeadFinder digest") -> str:
    out = [f"# {title}", "", f"_{len(leads)} leads matched. Sorted by relevance score._", ""]
    # Group by source for readability
    by_src: dict[str, List[Lead]] = {}
    for l in leads:
        by_src.setdefault(l.source, []).append(l)
    for src in sorted(by_src):
        out.append(f"## {src}")
        out.append("")
        for l in by_src[src]:
            budget = ", ".join(l.budget_signals) if l.budget_signals else "—"
            payment = ", ".join(l.payment_signals) if l.payment_signals else "—"
            out.append(f"### [{l.score}] {l.title}")
            out.append("")
            out.append(f"- **URL:** {l.url}")
            out.append(f"- **Budget:** {budget}")
            out.append(f"- **Payment:** {payment}")
            out.append(f"- **Author:** {l.author or '—'}  |  **Flair:** {l.flair or '—'}  |  **Age:** {l.age_hours:.1f}h  |  **Comments:** {l.num_comments}")
            if l.snippet:
                out.append("")
                out.append(f"> {l.snippet[:300]}")
            if l.outreach_draft:
                out.append("")
                out.append("**Draft outreach:**")
                out.append("")
                out.append("```")
                out.append(l.outreach_draft)
                out.append("```")
            out.append("")
        out.append("---")
        out.append("")
    return "\n".join(out)


def print_table(leads: List[Lead], *, limit: int = 25):
    """Rich pretty table — falls back to plain text if rich not installed."""
    try:
        from rich.console import Console
        from rich.table import Table
        c = Console()
        t = Table(show_lines=False, title=f"LeadFinder — top {min(limit,len(leads))} leads", title_style="bold cyan")
        t.add_column("Score", justify="right", style="bold yellow")
        t.add_column("Source", style="cyan")
        t.add_column("Title (truncated)", overflow="fold")
        t.add_column("Budget", style="green")
        t.add_column("Age", justify="right")
        t.add_column("URL", overflow="fold")
        for l in leads[:limit]:
            t.add_row(
                str(l.score),
                l.source,
                l.title[:80],
                ",".join(l.budget_signals) or "—",
                f"{l.age_hours:.0f}h",
                l.url,
            )
        c.print(t)
    except Exception:
        # Plain fallback
        for l in leads[:limit]:
            print(f"[{l.score:3d}] {l.source:30s} {l.title[:80]:80s} {l.url}")
