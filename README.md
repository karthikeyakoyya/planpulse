# PlanPulse: Supply Chain Planning Health and Action Tracker

A weekly planning-review kit for four markets (APAC, India, MENA-PAK, South Africa). It reads forecast, inventory, supply plan and open PO extracts, tells a planner what is off, and tracks who must act and by when.

**All data is simulated.** It is fictional and is never presented as real ISCP or company data. Every output says so.

## Run it

```bash
pip install -r requirements.txt
python -m pytest -q                              # 12 tests
python scripts/demo.py                           # two simulated weeks, writes outputs/
# or step by step
python -m planpulse simulate --as-of 2026-10-26
python -m planpulse run --as-of 2026-10-26
python -m planpulse approve --reviewer "Your Name"   # after reading outputs/draft_exception_summary.md
python -m planpulse report                           # rebuild Word and deck with the approved text
```

Ad-hoc questions (parameterized SQL in `sql/queries/`):

```bash
python -m planpulse query                                   # list queries
python -m planpulse query stockout --market APAC --weeks 4
python -m planpulse query cover --market India --max-days 14
python -m planpulse query late_po --supplier SUP-AP-02
python -m planpulse query actions --overdue-only
python -m planpulse query --sql "select market, count(*) from kpi_sku group by 1"   # read-only SELECT only
```

Turn meeting decisions into tracked actions: copy `docs/meeting_notes_template.md`, write `- ACTION: ... | owner: ... | due: YYYY-MM-DD | market: ...` lines, then `python -m planpulse meeting notes.md --date 2026-10-26`.

## What it does against the role

| Role need | PlanPulse |
|---|---|
| Data collection, analysis | `simulate.py` produces per-market extracts; DuckDB loads them; 10 SQL data-quality checks in `sql/dq_checks.sql`; KPIs in `sql/03_kpis.sql`; the numbers were cross-checked against an independent pandas recalculation |
| Documentation, reporting | Word status note, PowerPoint market deck, data dictionary (`docs/data_dictionary.md`) |
| Basic dashboards | Excel KPI workbook (formulas, not pasted values) and `outputs/dashboard.html` |
| AI, ML, automation | Scikit-learn baseline forecast, Isolation Forest, Claude-drafted summary with human approval, weekly GitHub Actions workflow |
| Supply chain domain | `docs/glossary.md`: lead time, safety stock, reorder point, days of cover, WAPE, bias, OTIF |
| Action items and timelines | Tracker with owner role, due date, status, overdue days, escalation level |
| Meetings and follow-up | Meeting notes template and `meeting` import command |
| Process gaps and risks | `docs/risk_register.csv`, `docs/gap_log.csv`, `docs/process_map.md` (Mermaid swimlane) |
| Organized records | One repo, this README, `docs/decision_log.md`, sample outputs in `outputs/` |
| Ad-hoc tasks | Parameterized query layer above |

## What the sample run shows (week of 2026-10-26, simulated)

- The data-quality checks found every defect the simulator injects on purpose (duplicate rows, negative stock, missing safety stock, null forecasts, PO dates out of order, orphan PO SKUs, a stale APAC snapshot, a negative sales row). A test asserts the counts match `data/raw/_injected_defects.json`.
- 112 exceptions (29 P1, 66 P2, 17 P3). 33 actions overdue; some already past their SLA and so at escalation level 2.
- The workbook formulas were recalculated with zero errors, and the Excel, dashboard and status draft all report the same totals (WAPE 20.9%, cover 53 days, OTIF 70.1%, 114 open actions).
- The dashboard has a stockout runway: 8 weeks of projected stock per at-risk SKU, with the week a new order would land outlined, so you can see which stockouts ordering can no longer fix.
- Baseline forecast, scored one week ahead on an 8-week holdout (WAPE, lower is better): system 20.9%, scikit-learn baseline 20.1%, 4-week moving average 20.5%, naive 26.6%. The "system" forecast here is itself simulated, with bias injected on a few SKUs, so the baseline winning proves nothing about a real planning system. What matters is the method: a fair one-week-ahead holdout against the incumbent and two naive rivals.

## Known limits

- Not run on GitHub yet. `.github/workflows/weekly.yml` is written but untested. The tracker database is kept between weekly runs with `actions/cache`, which is a convenience, not a durable store.
- The Claude-drafted summary has not been exercised against the live API (no key was available when this was built). Without `ANTHROPIC_API_KEY` it falls back to a template draft. Either way the draft stays `PENDING_APPROVAL` and is excluded from the Word note until a person runs `approve`. A check flags any number in the draft that is not in the computed facts. The model name is set by `PLANPULSE_MODEL` (default `claude-sonnet-5-5`); confirm it against current docs before relying on it.
- The Mermaid process map has not been rendered here. GitHub renders Mermaid in Markdown, so check it after you push.
- Week 2 of the demo keeps demand and master data and redraws the operational state (stock, POs, supply plan), so many week 1 exceptions resolve at once. That is a way to exercise carry-forward and auto-resolution, not a model of real week-to-week change.
- Owners are roles, not named people. Thresholds are generic; see `docs/decision_log.md`.
- The Excel file written by the pipeline has no cached values until Excel (or LibreOffice) opens and calculates it. The copy in `outputs/` was recalculated so previewers show numbers.

## Layout

```
planpulse/   simulate, pipeline, ml, actions, narrative, reports, queries, cli
sql/         dq_checks.sql, 02_clean.sql, 03_kpis.sql, 04_exceptions.sql, queries/
docs/        glossary, data dictionary, decision log, process map, risk register, gap log, meeting notes
tests/       12 tests: known-answer KPIs, defect detection, action lifecycle, meeting import, number check
outputs/     sample weekly outputs (Excel, Word, PowerPoint, HTML dashboard, CSVs, pending draft summary)
```

## Resume line (use it only after you have run and pushed this yourself)

"Built a simulated supply chain planning health tracker across four markets with forecasting, anomaly detection, an action tracker, and auto-generated status reports using Python, DuckDB, SQL, and Excel."
