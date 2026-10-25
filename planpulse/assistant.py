"""Planner assistant: answers a question by calling the saved read-only queries in sql/queries/.

With ANTHROPIC_API_KEY set it runs a small tool-use loop: the model may call one tool, `run_saved_query`, with a
query name and whitelisted parameters. It never writes SQL and never touches the tracker. Without a key (or if the
call fails) a keyword router picks one saved query, so the command always works offline.
Every number in a model answer is checked against the rows it was given, and unmatched numbers are reported.
"""
import json
import os
import re
from dataclasses import dataclass, field

from . import config as C
from . import queries
from .narrative import MODEL, numbers_not_in_facts

MAX_ROWS = 25
PARAMS = ("market", "supplier", "sku", "max_days", "weeks", "top", "status", "overdue_only")

SYSTEM = ("You help a supply chain planning team read a weekly health tracker. The data is SIMULATED, so say so. "
          "Answer only from rows returned by the run_saved_query tool; call it as many times as needed. "
          "If the tool returns no rows or an error, say that plainly. Do not invent causes, people or dates. "
          "Keep the answer under 120 words and name the query you used.")


def tool_spec() -> dict:
    return {
        "name": "run_saved_query",
        "description": "Run one saved read-only planning query and get its rows (at most %d)." % MAX_ROWS,
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "enum": queries.available()},
                "market": {"type": "string", "enum": list(C.MARKETS)},
                "supplier": {"type": "string"}, "sku": {"type": "string"}, "status": {"type": "string"},
                "max_days": {"type": "integer"}, "weeks": {"type": "integer"}, "top": {"type": "integer"},
                "overdue_only": {"type": "boolean"},
            },
            "required": ["name"],
        },
    }


@dataclass
class Answer:
    text: str
    source: str                                   # "claude:<model>", "keyword router" or a fallback note
    trace: list = field(default_factory=list)     # (query name, params, rows returned)
    unmatched_numbers: list = field(default_factory=list)


def _clean_params(raw: dict) -> dict:
    p = {k: raw[k] for k in PARAMS if raw.get(k) is not None}
    if p.get("market") not in (None, *C.MARKETS):
        p.pop("market")
    for k in ("max_days", "weeks", "top"):
        if k in p:
            p[k] = int(p[k])
    return p


def _run_tool(args: dict, con, trace: list, seen_rows: list) -> str:
    name = args.get("name")
    if name not in queries.available():
        return json.dumps({"error": f"unknown query '{name}'", "available": queries.available()})
    params = _clean_params(args)
    df = queries.run(name, params, con=con)
    trace.append((name, params, len(df)))
    rows = json.loads(df.head(MAX_ROWS).to_json(orient="records", date_format="iso"))
    seen_rows.extend(rows)
    return json.dumps({"query": name, "rows_total": len(df), "rows_shown": len(rows), "rows": rows})


# ---- offline router -------------------------------------------------------------------------------------------
ROUTES = [  # first match wins, so the specific phrases sit above the general ones
    (r"overdue.*(action|task)|(action|task).*overdue|escalat", "actions", {"overdue_only": True}),
    (r"\baction|\btask|follow.?up", "actions", {}),
    (r"stock.?out|run(s)? out|running out|shortage", "stockout", {}),
    (r"late|delay|past due|overdue po", "late_po", {}),
    (r"otif|on.?time|in full|supplier perform", "otif", {}),
    (r"excess|overstock|too much stock", "excess", {}),
    (r"cover|low stock|safety stock", "cover", {}),
]
SKU_RE = re.compile(r"\b[A-Z]{2}-[A-Z]{3}-\d{3}\b")
MARKET_WORDS = {"apac": "APAC", "india": "India", "mena": "MENA-PAK", "pak": "MENA-PAK", "south africa": "South Africa", "africa": "South Africa"}


def route(question: str) -> tuple[str, dict] | None:
    q = question.lower()
    sku = SKU_RE.search(question)
    if sku:
        return "sku", {"sku": sku.group(0)}
    for pattern, name, fixed in ROUTES:
        if re.search(pattern, q):
            params = dict(fixed)
            for word, market in MARKET_WORDS.items():
                if word in q:
                    params["market"] = market
                    break
            for key, rx in (("weeks", r"(\d+)\s*week"), ("max_days", r"(\d+)\s*day"), ("top", r"top\s*(\d+)")):
                m = re.search(rx, q)
                if m:
                    params[key] = int(m.group(1))
            return name, params
    return None


def _router_answer(question: str, con, note: str) -> Answer:
    hit = route(question)
    if hit is None:
        return Answer("No saved query matches that question. Try: " + ", ".join(queries.available()) + ".", note)
    name, params = hit
    df = queries.run(name, params, con=con)
    body = df.head(15).to_string(index=False) if len(df) else "(no rows)"
    more = f"\n... {len(df) - 15} more rows" if len(df) > 15 else ""
    return Answer(f"Simulated data. Query '{name}' {params or ''}:\n{body}{more}", note, [(name, params, len(df))])


# ---- model loop -----------------------------------------------------------------------------------------------
def make_client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=key)
    except Exception:
        return None


def ask(question: str, con, client="auto", model: str = MODEL, max_steps: int = 4) -> Answer:
    client = make_client() if client == "auto" else client
    if client is None:
        return _router_answer(question, con, "keyword router (no ANTHROPIC_API_KEY)")
    messages = [{"role": "user", "content": question}]
    trace, seen = [], []
    try:
        for _ in range(max_steps):
            resp = client.messages.create(model=model, max_tokens=800, system=SYSTEM, tools=[tool_spec()], messages=messages)
            if resp.stop_reason != "tool_use":
                text = "".join(b.text for b in resp.content if b.type == "text").strip()
                facts = {"question": question, "rows": seen}
                return Answer(text, f"claude:{model}", trace, numbers_not_in_facts(text, facts))
            messages.append({"role": "assistant", "content": resp.content})
            results = [{"type": "tool_result", "tool_use_id": b.id, "content": _run_tool(dict(b.input), con, trace, seen)}
                       for b in resp.content if b.type == "tool_use"]
            messages.append({"role": "user", "content": results})
        return Answer("Stopped after the step limit without a final answer.", f"claude:{model}", trace)
    except Exception as e:   # network, auth, bad response: fall back, never leave the planner without an answer
        return _router_answer(question, con, f"keyword router (model call failed: {type(e).__name__})")
