"""Parameterized ad-hoc query layer. Each query is a .sql file in sql/queries with $named parameters."""
import re

from . import config as C
from .pipeline import connect

QDIR = C.SQL_DIR / "queries"


def available():
    return sorted(p.stem for p in QDIR.glob("*.sql"))


def run(name: str, params: dict | None = None, con=None):
    path = QDIR / f"{name}.sql"
    if not path.exists():
        raise SystemExit(f"Unknown query '{name}'. Available: {', '.join(available())}")
    sql = path.read_text(encoding="utf-8")
    wanted = set(re.findall(r"\$(\w+)", sql))
    given = {k: v for k, v in (params or {}).items() if k in wanted}
    given = {k: given.get(k) for k in wanted}   # unset optional params become NULL
    for k, v in list(given.items()):
        if isinstance(v, str) and k in ("max_days", "weeks", "top") and v.isdigit():
            given[k] = int(v)
    own = con is None
    con = con or connect(read_only=True)
    try:
        return con.execute(sql, given).df()
    finally:
        if own:
            con.close()


def read_only_sql(sql: str, con=None):
    if not re.match(r"^\s*(with|select)\b", sql, re.I) or re.search(r"\b(insert|update|delete|drop|create|alter|attach|copy)\b", sql, re.I):
        raise SystemExit("Only single read-only SELECT statements are allowed.")
    own = con is None
    con = con or connect(read_only=True)
    try:
        return con.execute(sql).df()
    finally:
        if own:
            con.close()
