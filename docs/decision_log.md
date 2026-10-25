# Decision log

Each decision names the choice, the reason, and what would change it. Thresholds live in `planpulse/config.py`.

| # | Decision | Why | Revisit when |
|---|---|---|---|
| D01 | All data is simulated and labelled as such in every output | No access to real ISCP data; avoids implying otherwise | Never presented as real |
| D02 | Rows that fail hard rules (negative stock, orphan PO SKU, promised before order, null forecast, negative sales) are quarantined, not repaired | Repairing silently hides the source problem; each failure raises a data action instead | A market agrees a repair rule |
| D03 | Duplicate inventory rows are collapsed with DISTINCT | Exact duplicates add no information | Duplicates start differing in values |
| D04 | Projected receipts = open POs not past due + planned orders not yet placed; past-due POs are excluded | Counting both PO and PLANNED double counts; a past-due PO has no reliable arrival date | Procurement supplies a re-promised date field (gap G02) |
| D05 | Stockout risk HIGH when projected stockout is sooner than the lead time | A new order cannot arrive in time, so it needs expediting | Lead time data proves unreliable |
| D06 | Days of cover uses the next 4 weeks of forecast | Short enough to reflect near-term demand, long enough to smooth one odd week | Seasonal categories need a longer window |
| D07 | Accuracy window 8 complete weeks, lag-1 forecast, WAPE and bias at SKU and market level | Standard pair: WAPE for size of miss, bias for direction | Planners want lag-2 or lag-4 accuracy |
| D08 | OTIF = on time (received <= promised) and in full (>= 98% of ordered), trailing 26 weeks | Common definition with a small tolerance for rounding | The business uses a different tolerance |
| D09 | Bias exception only when abs(bias) > 20% and 8-week actuals >= 200 units | Avoids noise from tiny SKUs | Volume bands per category |
| D10 | Excess stock = cover above 120 days | Generic threshold | Category-specific targets exist |
| D11 | The ML baseline is a benchmark, not a replacement for the system forecast | It is scored one week ahead on a holdout against the system forecast, 4-week moving average and naive | Baseline consistently beats the system on real data |
| D12 | Isolation Forest only raises an exception when no rule already flags the SKU | Keeps ML for what rules miss; avoids duplicate actions | Rules and anomalies overlap by design |
| D13 | The drafted exception summary sees only aggregated facts, is number-checked, and stays PENDING until a person runs `approve` | A person owns what goes to stakeholders | Never remove the approval step |
| D14 | Action owners are roles, not names | Data is simulated; names would be invented | The team maps roles to people |
| D15 | SLA by priority: P1 2 days, P2 5 days, P3 10 days. Escalation level 1 when overdue within the SLA, level 2 when overdue longer than the SLA | Simple and explainable | Team agrees its own SLAs |
| D16 | An action whose exception is no longer flagged moves to Resolved-Verify, not Closed | The owner confirms, so a data glitch cannot close a real problem | Auto-close is trusted |
| D17 | Duplicate-key actions are never created; a reappearing exception on a closed action opens a new action | Keeps history and avoids reopening old records | |
| D18 | DuckDB for storage and SQL for every KPI; Python only orchestrates, models and renders | Logic is reviewable as plain SQL | Data size outgrows a single file |
| D19 | Market and SKU forecast accuracy use every SKU that has sales and a forecast, even if the SKU is held out of stock KPIs for bad inventory data | Stock data problems must not change forecast accuracy; found when an independent recalculation disagreed with the market figure | Never |
| D20 | Late POs always raise an exception, even when their SKU is held out of stock KPIs | A PO on a SKU with bad stock data is exactly what needs a person | Never |
| D21 | ML baseline SKU scaling uses training weeks only | Scaling on all weeks leaked the holdout level into the benchmark | Never |
