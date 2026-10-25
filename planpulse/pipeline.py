"""Load per-market extracts into DuckDB, run data-quality checks, build the clean layer and KPIs."""
import re
from pathlib import Path

import duckdb
import pandas as pd

from . import config as C

TABLES = {  # raw table -> extract file name
    "raw_sales": "sales_actuals.csv",
    "raw_forecast": "forecast.csv",
    "raw_inventory": "inventory.csv",
    "raw_supply_plan": "supply_plan.csv",
    "raw_po": "po.csv",
}


def render(sql: str) -> str:
    """Fill {{TOKENS}} from config so thresholds are defined in exactly one place."""
    tokens = {
        "HORIZON": C.HORIZON_WEEKS, "ACC": C.ACCURACY_WEEKS, "OTIF": C.OTIF_WEEKS,
        "TOL": C.OTIF_IN_FULL_TOLERANCE, "EXCESS": C.EXCESS_COVER_DAYS, "BIAS": C.BIAS_THRESHOLD,
        "BIAS_MIN": C.BIAS_MIN_UNITS, "LATE_P1": C.LATE_PO_P1_DAYS, "FRESH": C.FRESHNESS_MAX_DAYS,
    }
    for k, v in tokens.items():
        sql = sql.replace("{{" + k + "}}", str(v))
    return sql


def connect(path=C.DB_PATH, read_only=False) -> duckdb.DuckDBPyConnection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path), read_only=read_only)


def run_sql_file(con, name: str):
    con.execute(render((C.SQL_DIR / name).read_text(encoding="utf-8")))


def load_raw(con, raw_dir: Path, as_of: str):
    con.execute("CREATE OR REPLACE TABLE params AS SELECT DATE '%s' AS as_of" % as_of)
    for table, fname in TABLES.items():
        files = sorted(Path(raw_dir).glob(f"*/{fname}"))
        if not files:
            raise FileNotFoundError(f"No {fname} extracts under {raw_dir}")
        glob = str(Path(raw_dir) / "*" / fname)
        con.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM read_csv('{glob}', header=true)")


def parse_checks(text: str):
    blocks = re.split(r"^-- check:\s*", text, flags=re.M)[1:]
    out = []
    for b in blocks:
        head, _, body = b.partition("\n")
        cid, sev, desc = [x.strip() for x in head.split("|", 2)]
        out.append(dict(check_id=cid, severity=sev, description=render(desc), sql=render(body.strip().rstrip(";"))))
    return out


def run_dq(con) -> pd.DataFrame:
    checks = parse_checks((C.SQL_DIR / "dq_checks.sql").read_text(encoding="utf-8"))
    markets = list(C.MARKETS)
    rows = []
    for ck in checks:
        res = dict((m, int(n)) for m, n in con.execute(ck["sql"]).fetchall())
        for m in markets:
            rows.append((m, ck["check_id"], ck["severity"], ck["description"], res.get(m, 0)))
    df = pd.DataFrame(rows, columns=["market", "check_id", "severity", "description", "n_fail"])
    df["status"] = df.n_fail.map(lambda n: "FAIL" if n else "PASS")
    con.execute("CREATE OR REPLACE TABLE dq_results AS SELECT * FROM df")
    return df


def quarantine_counts(con) -> pd.DataFrame:
    q = con.execute("""
      SELECT market, 'inventory' AS tbl, COUNT(*) AS raw_rows FROM raw_inventory GROUP BY market UNION ALL
      SELECT market, 'inventory_clean', COUNT(*) FROM inv_clean GROUP BY market UNION ALL
      SELECT market, 'po', COUNT(*) FROM raw_po GROUP BY market UNION ALL
      SELECT market, 'po_clean', COUNT(*) FROM po_clean GROUP BY market""").df()
    return q


def build(con, raw_dir: Path = C.DATA_RAW, as_of: str = C.DEFAULT_AS_OF) -> pd.DataFrame:
    load_raw(con, raw_dir, as_of)
    dq = run_dq(con)
    run_sql_file(con, "02_clean.sql")
    run_sql_file(con, "03_kpis.sql")
    run_sql_file(con, "04_exceptions.sql")
    return dq
