"""Turn exceptions into tracked actions: owner role, due date, status, overdue flag, escalation level.

Owners are ROLES (for example "Supply Planner, APAC"), because the data is simulated and there are
no real people to assign. A team using this would map roles to names in OWNER_ROLE below.
"""
import re
from datetime import date, timedelta

import pandas as pd

from . import config as C

OWNER_ROLE = {
    "STOCKOUT_RISK": "Supply Planner", "BELOW_SAFETY": "Supply Planner", "LATE_PO": "Procurement Lead",
    "SUPPLIER_OTIF": "Procurement Lead", "FORECAST_BIAS": "Demand Planner", "FORECAST_DIVERGENCE": "Demand Planner",
    "EXCESS_STOCK": "Inventory Planner", "DATA_QUALITY": "Data Steward", "UNEXPLAINED_ANOMALY": "Planning Analyst",
}
SEV_FROM_DQ = {"HIGH": "P1", "MEDIUM": "P2", "LOW": "P3"}
OPEN_STATES = ("Open", "In Progress")
STATES = ("Open", "In Progress", "Resolved-Verify", "Closed")
ESCALATE_TO = {1: "Market lead", 2: "ISCP lead"}

ACTION_COLS = ["action_id", "key", "market", "exc_type", "ref", "severity", "owner_role", "description", "created_week",
               "due_date", "status", "closed_date", "last_seen", "days_overdue", "escalation_level", "source", "note"]


def assemble_exceptions(con, dq: pd.DataFrame, divergence: pd.DataFrame, anomalies: pd.DataFrame) -> pd.DataFrame:
    rules = con.execute("SELECT * FROM exceptions_rules").df()
    rows = []
    for r in dq[dq.n_fail > 0].itertuples():
        rows.append(dict(market=r.market, exc_type="DATA_QUALITY", severity=SEV_FROM_DQ[r.severity], ref=r.check_id,
                         sku=None, supplier=None, metric=float(r.n_fail), detail=f"{r.description}: {r.n_fail} row(s)"))
    for r in divergence.itertuples():
        rows.append(dict(market=r.market, exc_type="FORECAST_DIVERGENCE", severity="P3", ref=r.sku, sku=r.sku, supplier=None,
                         metric=float(r.gap_pct), detail=f"System 4-week forecast {r.system:.0f} vs ML baseline {r.ml:.0f} ({r.gap_pct * 100:+.0f}%)"))
    flagged = set(zip(rules.market, rules.sku.fillna("")))
    for r in anomalies[anomalies.anomaly].itertuples():
        if (r.market, r.sku) in flagged:
            continue  # already explained by a rule; the anomaly adds nothing
        rows.append(dict(market=r.market, exc_type="UNEXPLAINED_ANOMALY", severity="P3", ref=r.sku, sku=r.sku, supplier=None,
                         metric=float(r.score), detail=f"Isolation Forest flag, no rule exception on this SKU. Most unusual feature: {r.driver} (z={r.driver_z:+.1f})"))
    out = pd.concat([rules, pd.DataFrame(rows)], ignore_index=True)
    out["key"] = out.market + "|" + out.exc_type + "|" + out.ref.astype(str)
    out["owner_role"] = out.exc_type.map(OWNER_ROLE) + ", " + out.market
    return out


def _empty():
    return pd.DataFrame(columns=ACTION_COLS)


def load_actions(con) -> pd.DataFrame:
    tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
    if "actions" not in tables:
        return _empty()
    return con.execute("SELECT * FROM actions ORDER BY action_id").df()


def save_actions(con, df: pd.DataFrame):
    df = df[ACTION_COLS].copy()
    for c in ["created_week", "due_date", "closed_date", "last_seen"]:
        df[c] = pd.to_datetime(df[c]).dt.date
    con.execute("CREATE OR REPLACE TABLE actions AS SELECT * FROM df")


def _next_id(df: pd.DataFrame) -> int:
    if df.empty:
        return 1
    return int(df.action_id.str.replace("ACT-", "").astype(int).max()) + 1


def refresh_flags(df: pd.DataFrame, as_of: date) -> pd.DataFrame:
    df = df.copy()
    for i, r in df.iterrows():
        if r.status in OPEN_STATES and pd.notna(r.due_date):
            od = max(0, (as_of - pd.Timestamp(r.due_date).date()).days)
            sla = C.SLA_DAYS.get(r.severity, 10)
            df.at[i, "days_overdue"] = od
            df.at[i, "escalation_level"] = 0 if od == 0 else (1 if od <= sla else 2)
        else:
            df.at[i, "days_overdue"], df.at[i, "escalation_level"] = 0, 0
    return df


def sync_actions(con, exceptions: pd.DataFrame, as_of_str: str) -> pd.DataFrame:
    as_of = date.fromisoformat(as_of_str)
    cur = load_actions(con)
    n = _next_id(cur)
    seen = set(exceptions.key)
    new_rows = []
    for e in exceptions.itertuples():
        m = cur[(cur.key == e.key) & (cur.status != "Closed")]
        if len(m):
            i = m.index[0]
            cur.at[i, "last_seen"] = pd.Timestamp(as_of)
            cur.at[i, "description"] = e.detail
            if cur.at[i, "status"] == "Resolved-Verify":
                cur.at[i, "status"] = "Open"
                cur.at[i, "note"] = f"Reappeared in run {as_of}"
            continue
        new_rows.append(dict(action_id=f"ACT-{n:04d}", key=e.key, market=e.market, exc_type=e.exc_type, ref=str(e.ref),
                             severity=e.severity, owner_role=e.owner_role, description=e.detail, created_week=pd.Timestamp(as_of),
                             due_date=pd.Timestamp(as_of + timedelta(days=C.SLA_DAYS[e.severity])), status="Open", closed_date=pd.NaT,
                             last_seen=pd.Timestamp(as_of), days_overdue=0, escalation_level=0, source="exception", note=""))
        n += 1
    if new_rows:
        cur = pd.concat([cur, pd.DataFrame(new_rows)], ignore_index=True) if len(cur) else pd.DataFrame(new_rows)
    gone = cur[(cur.source == "exception") & cur.status.isin(OPEN_STATES) & ~cur.key.isin(seen)].index
    for i in gone:
        cur.at[i, "status"] = "Resolved-Verify"
        cur.at[i, "note"] = f"Not flagged in run {as_of}; owner to confirm and close"
    cur = refresh_flags(cur, as_of)
    save_actions(con, cur)
    return cur


def update_action(con, action_id: str, status: str | None, note: str | None, on: str, as_of_str: str | None = None):
    if status and status not in STATES:
        raise ValueError(f"status must be one of {STATES}")
    df = load_actions(con)
    if action_id not in set(df.action_id):
        raise KeyError(action_id)
    i = df.index[df.action_id == action_id][0]
    if status:
        df.at[i, "status"] = status
        df.at[i, "closed_date"] = pd.Timestamp(on) if status == "Closed" else pd.NaT
    if note:
        df.at[i, "note"] = note
    df = refresh_flags(df, date.fromisoformat(as_of_str or on))
    save_actions(con, df)


MEETING_RE = re.compile(r"^-\s*ACTION:\s*(?P<text>.+?)\s*\|\s*owner:\s*(?P<owner>.+?)\s*\|\s*due:\s*(?P<due>\d{4}-\d{2}-\d{2})\s*\|\s*market:\s*(?P<market>.+?)\s*$")


def import_meeting(con, path, meeting_date: str, as_of_str: str) -> int:
    """Read '- ACTION: text | owner: role | due: YYYY-MM-DD | market: X' lines from a notes file."""
    cur = load_actions(con)
    n = _next_id(cur)
    new = []
    for line in open(path, encoding="utf-8"):
        m = MEETING_RE.match(line.strip())
        if not m:
            continue
        key = f"{m['market']}|MEETING|{meeting_date}|{m['text'][:40]}"
        if len(cur) and (cur.key == key).any():
            continue
        new.append(dict(action_id=f"ACT-{n:04d}", key=key, market=m["market"], exc_type="MEETING", ref=meeting_date,
                        severity="P2", owner_role=m["owner"], description=m["text"], created_week=pd.Timestamp(meeting_date),
                        due_date=pd.Timestamp(m["due"]), status="Open", closed_date=pd.NaT,
                        last_seen=pd.Timestamp(meeting_date), days_overdue=0, escalation_level=0, source="meeting", note=""))
        n += 1
    if new:
        cur = pd.concat([cur, pd.DataFrame(new)], ignore_index=True) if len(cur) else pd.DataFrame(new)
    cur = refresh_flags(cur, date.fromisoformat(as_of_str))
    save_actions(con, cur)
    return len(new)
