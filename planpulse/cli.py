"""Command line entry point: python -m planpulse <command>."""
import argparse
from datetime import date

import pandas as pd

from . import actions as A
from . import config as C
from . import ml, narrative, pipeline, queries, reports, simulate


def run_week(as_of: str, raw_dir=C.DATA_RAW, db=C.DB_PATH, out_dir=C.OUT_DIR, quiet=False):
    log = (lambda *a: None) if quiet else print
    con = pipeline.connect(db)
    dq = pipeline.build(con, raw_dir, as_of)
    log(f"[{as_of}] loaded extracts, DQ failures: {int((dq.n_fail > 0).sum())} checks across markets")
    bench, nxt = ml.baseline_forecast(con)
    div = ml.divergence(con, nxt)
    an = ml.anomalies(con)
    con.execute("CREATE OR REPLACE TABLE ml_benchmark AS SELECT * FROM bench")
    con.execute("CREATE OR REPLACE TABLE ml_forecast AS SELECT * FROM nxt")
    exc = A.assemble_exceptions(con, dq, div, an)
    con.execute("CREATE OR REPLACE TABLE exceptions AS SELECT * FROM exc")
    act = A.sync_actions(con, exc, as_of)
    log(f"[{as_of}] {len(exc)} exceptions, {len(act)} actions tracked, {int((act.days_overdue > 0).sum())} overdue")
    facts = narrative.build_facts(con, exc, act, as_of)
    narrative.write_draft(facts)
    g = reports.gather(con, as_of)
    reports.write_all(g, out_dir)
    log(f"[{as_of}] outputs written to {out_dir}")
    con.close()
    return g


def main(argv=None):
    p = argparse.ArgumentParser(prog="planpulse", description="Supply chain planning health tracker (simulated data)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("simulate", help="generate fictional per-market extracts")
    s.add_argument("--as-of", default=C.DEFAULT_AS_OF)
    s.add_argument("--seed", type=int, default=42)

    r = sub.add_parser("run", help="run the weekly cycle")
    r.add_argument("--as-of", default=C.DEFAULT_AS_OF)

    q = sub.add_parser("query", help="ad-hoc parameterized query")
    q.add_argument("name", nargs="?", help="query name; omit to list")
    q.add_argument("--market"); q.add_argument("--supplier"); q.add_argument("--sku")
    q.add_argument("--max-days"); q.add_argument("--weeks"); q.add_argument("--top")
    q.add_argument("--status"); q.add_argument("--overdue-only", action="store_true")
    q.add_argument("--sql", help="free read-only SELECT instead of a named query")

    u = sub.add_parser("action", help="update an action")
    u.add_argument("action_id"); u.add_argument("--status", choices=A.STATES); u.add_argument("--note")
    u.add_argument("--on", default=date.today().isoformat(), help="date of the update, default today")

    m = sub.add_parser("meeting", help="import '- ACTION:' lines from a meeting notes file")
    m.add_argument("file"); m.add_argument("--date", required=True); m.add_argument("--as-of", default=C.DEFAULT_AS_OF)

    sub.add_parser("report", help="rebuild reports from the database (use after approve or action updates)").add_argument("--as-of", default=C.DEFAULT_AS_OF)

    a = sub.add_parser("approve", help="approve the drafted exception summary")
    a.add_argument("--reviewer", required=True)

    args = p.parse_args(argv)
    if args.cmd == "simulate":
        simulate.simulate(as_of=args.as_of, seed=args.seed)
        print(f"Wrote simulated extracts to {C.DATA_RAW}. Injected defects: data/raw/_injected_defects.json")
    elif args.cmd == "run":
        run_week(args.as_of)
    elif args.cmd == "query":
        if args.sql:
            df = queries.read_only_sql(args.sql)
        elif not args.name:
            print("Available queries:", ", ".join(queries.available()))
            return
        else:
            params = dict(market=args.market, supplier=args.supplier, sku=args.sku, max_days=args.max_days, weeks=args.weeks,
                          top=args.top, status=args.status, overdue_only=args.overdue_only)
            df = queries.run(args.name, params)
        with pd.option_context("display.width", 200, "display.max_columns", 30):
            print(df.to_string(index=False) if len(df) else "(no rows)")
    elif args.cmd == "action":
        con = pipeline.connect()
        A.update_action(con, args.action_id, args.status, args.note, args.on)
        print(f"{args.action_id} updated")
    elif args.cmd == "meeting":
        con = pipeline.connect()
        n = A.import_meeting(con, args.file, args.date, args.as_of)
        print(f"{n} action(s) imported from {args.file}")
    elif args.cmd == "report":
        con = pipeline.connect()
        reports.write_all(reports.gather(con, args.as_of), C.OUT_DIR)
        print(f"Reports rebuilt in {C.OUT_DIR}")
    elif args.cmd == "approve":
        path = narrative.approve(args.reviewer)
        print(f"Approved: {path}. Run `python -m planpulse report` to put it into the Word note and deck.")


if __name__ == "__main__":
    main()
