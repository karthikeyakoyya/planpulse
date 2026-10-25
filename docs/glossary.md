# Glossary

Plain definitions of the supply chain terms PlanPulse uses, each with where it appears in the code.

| Term | Meaning | In PlanPulse |
|---|---|---|
| Lead time | Days from placing an order to receiving it | `inventory.lead_time_days` |
| Safety stock | Extra stock held to absorb demand and supply variation | `inventory.safety_stock`; exception BELOW_SAFETY |
| Reorder point | Stock level at which a new order should be placed: demand during lead time plus safety stock | Used in the explanation of risk; the simulator builds safety stock as 1.65 x demand sigma x sqrt(lead time in weeks) |
| Days of cover | How many days current stock lasts at forecast demand: on hand / (average weekly forecast / 7) | `kpi_sku.days_of_cover` |
| Stockout risk | (Weeks are numbered 1 to 8, week 1 being the current week.) Whether projected stock goes below zero in the next 8 weeks, and whether a new order could still arrive in time | HIGH if projected stockout is sooner than lead time, MEDIUM if later, LOW if none |
| Forecast accuracy (WAPE) | Weighted absolute percentage error: sum of absolute errors / sum of actuals. Lower is better | `kpi_accuracy_sku.wape` |
| Forecast bias | Net direction of error: (sum forecast - sum actual) / sum actual. Positive means over-forecasting | `kpi_accuracy_sku.bias` |
| OTIF | On time and in full: share of received POs that arrived on or before the promised date and with at least 98% of the ordered quantity | `kpi_otif_supplier` |
| Open PO | Purchase order not yet fully received | `po.status = 'Open'` |
| Supply plan | Planned receipts by week. PlanPulse splits them into PO (already placed) and PLANNED (not yet placed) so nothing is counted twice | `supply_plan.source` |
| Excess stock | Stock above a cover threshold (120 days by default), valued at unit cost | `kpi_sku.excess_value` |
| Exception | Something that is off and needs a person to act | `exceptions` table |
| P1 / P2 / P3 | Priority with a response SLA of 2 / 5 / 10 days | `config.SLA_DAYS` |
| Escalation | Overdue actions move up: level 1 to market lead, level 2 (overdue longer than the SLA) to ISCP lead | `actions.escalation_level` |
