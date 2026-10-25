"""Draft the weekly exception summary and hold it for human approval.

Flow: facts (computed in SQL/pandas) -> draft (Claude if ANTHROPIC_API_KEY is set, else a template)
-> number check -> saved as PENDING -> a person runs `planpulse approve --reviewer NAME` -> reports include it.
Unapproved drafts never go into the Word note or the deck. The model only sees aggregated facts, never raw rows.
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import config as C

MODEL = os.environ.get("PLANPULSE_MODEL", "claude-sonnet-5-5")
DRAFT = C.OUT_DIR / "draft_exception_summary.md"
APPROVED = C.OUT_DIR / "approved_exception_summary.md"


def build_facts(con, exceptions: pd.DataFrame, actions: pd.DataFrame, as_of: str) -> dict:
    km = con.execute("SELECT * FROM kpi_market ORDER BY market").df()
    markets = {}
    for r in km.itertuples():
        ex = exceptions[exceptions.market == r.market]
        p1 = ex[ex.severity == "P1"]
        markets[r.market] = dict(
            wape_pct=round(r.wape * 100, 1), bias_pct=round(r.bias * 100, 1), avg_days_cover=round(r.avg_days_cover, 0),
            high_stockout_risk_skus=int(r.high_risk_skus), late_pos=int(r.late_pos), otif_pct=round(r.otif * 100, 1),
            p1_exceptions=int(len(p1)), total_exceptions=int(len(ex)),
            top_p1=[f"{x.exc_type}: {x.detail}" for x in p1.head(3).itertuples()])
    ov = actions[(actions.status.isin(["Open", "In Progress"])) & (actions.days_overdue > 0)]
    return dict(as_of=as_of, markets=markets, open_actions=int(actions.status.isin(["Open", "In Progress"]).sum()),
                overdue_actions=int(len(ov)), escalated_l2=int((ov.escalation_level == 2).sum()))


PROMPT = """You are drafting the weekly planning-health summary for a supply chain planning team.
The data is SIMULATED, so say so in the first line. Use ONLY the numbers in the JSON facts below.
Do not invent causes, people or dates. Write 150 to 220 words, plain language, no em dashes.
Structure: one headline sentence, then one short paragraph per market naming what needs action and which
role owns it, then one sentence on overdue actions. If a fact is missing, say it is not available.

FACTS:
{facts}
"""


def template_draft(facts: dict) -> str:
    lines = [f"Simulated data, week of {facts['as_of']}. {facts['open_actions']} actions are open and {facts['overdue_actions']} are overdue "
             f"({facts['escalated_l2']} at the second escalation level)."]
    for m, d in facts["markets"].items():
        top = f" Top priority: {d['top_p1'][0]}." if d["top_p1"] else ""
        lines.append(f"{m}: forecast WAPE {d['wape_pct']}% with bias {d['bias_pct']}%, average cover {d['avg_days_cover']:.0f} days, OTIF {d['otif_pct']}%. "
                     f"{d['high_stockout_risk_skus']} SKUs at high stockout risk and {d['late_pos']} late POs; {d['p1_exceptions']} P1 exceptions.{top}")
    return "\n\n".join(lines)


def claude_draft(facts: dict) -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(model=MODEL, max_tokens=700,
                                     messages=[{"role": "user", "content": PROMPT.format(facts=json.dumps(facts, indent=1))}])
        return "".join(b.text for b in msg.content if b.type == "text").strip()
    except Exception as e:  # network, auth, missing package: fall back, never block the weekly run
        print(f"[narrative] Claude call failed ({type(e).__name__}); using template draft")
        return None


def numbers_not_in_facts(text: str, facts: dict) -> list[str]:
    blob = json.dumps(facts)
    have = set(re.findall(r"\d+(?:\.\d+)?", blob))
    have |= {str(int(float(x))) for x in have}
    bad = []
    for n in re.findall(r"\d+(?:\.\d+)?", text):
        if n in have or n in {"0", "1", "2", "3", "4", "8", "26", "52"} or re.fullmatch(r"\d{4}", n):
            continue
        bad.append(n)
    return sorted(set(bad))


def write_draft(facts: dict) -> Path:
    text = claude_draft(facts)
    source = f"claude:{MODEL}" if text else "template (no ANTHROPIC_API_KEY or call failed)"
    text = text or template_draft(facts)
    flagged = numbers_not_in_facts(text, facts)
    C.OUT_DIR.mkdir(exist_ok=True, parents=True)
    head = (f"---\nstatus: PENDING_APPROVAL\nas_of: {facts['as_of']}\ngenerated_by: {source}\n"
            f"numbers_not_in_facts: {flagged}\n---\n")
    DRAFT.write_text(head + text + "\n", encoding="utf-8")
    if APPROVED.exists():
        APPROVED.unlink()   # a new draft retires last week's approval
    return DRAFT


def approve(reviewer: str) -> Path:
    if not DRAFT.exists():
        raise FileNotFoundError("No draft to approve. Run `planpulse run` first.")
    body = DRAFT.read_text(encoding="utf-8")
    if "numbers_not_in_facts: []" not in body:
        print("WARNING: draft contains numbers that are not in the computed facts. Edit the draft before approving.")
    body = body.replace("status: PENDING_APPROVAL", f"status: APPROVED\nreviewer: {reviewer}\napproved_at: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    APPROVED.write_text(body, encoding="utf-8")
    return APPROVED


def read_approved() -> tuple[str | None, str]:
    """Returns (text or None, status string for the report footer)."""
    if APPROVED.exists():
        raw = APPROVED.read_text(encoding="utf-8")
        _, fm, text = raw.split("---\n", 2)
        rev = re.search(r"reviewer: (.+)", fm)
        return text.strip(), f"Approved by {rev.group(1) if rev else 'reviewer'}"
    return None, "Exception summary draft is pending human approval and is not included."
