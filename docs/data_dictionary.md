# Data dictionary

All extracts are simulated (see `planpulse/simulate.py`). One folder per market under `data/raw/`.

## Extracts (raw layer)

### sales_actuals.csv (raw_sales)
| Column | Meaning |
|---|---|
| market | One of APAC, India, MENA-PAK, South Africa |
| sku | SKU id, for example AP-DEV-001 |
| week_start | Monday of the week |
| units | Units sold that week. Negative values fail check SALES_NEG |

### forecast.csv (raw_forecast)
| Column | Meaning |
|---|---|
| market | Market name |
| sku | SKU id |
| week_start | Monday of the week. Past weeks hold the lag-1 forecast made the week before; future weeks hold the current forecast |
| forecast_units | Forecast units. Null fails check FC_NULL |

### inventory.csv (raw_inventory)
| Column | Meaning |
|---|---|
| market | Market name |
| sku | SKU id (the SKU master) |
| category | Devices, Accessories, Network or Storage |
| snapshot_date | Date the stock snapshot was taken |
| on_hand | Units on hand. Negative fails INV_NEG_ONHAND |
| safety_stock | Safety stock units. Null fails INV_NULL_SS |
| lead_time_days | Supplier lead time in days |
| unit_cost | Cost per unit in simulated currency |

### supply_plan.csv (raw_supply_plan)
| Column | Meaning |
|---|---|
| market | Market name |
| sku | SKU id |
| week_start | Week the receipt is planned |
| planned_qty | Units planned to arrive |
| source | PO if backed by an open PO, PLANNED if the order is not yet placed |

### po.csv (raw_po)
| Column | Meaning |
|---|---|
| po_id | Purchase order id |
| market | Market name |
| sku | SKU id. Must exist in inventory (check PO_ORPHAN) |
| supplier | Supplier id |
| order_date | Date the PO was placed |
| promised_date | Date the supplier promised delivery (must not precede order_date) |
| ordered_qty | Units ordered |
| received_qty | Units received so far |
| received_date | Date received; empty for open POs |
| status | Open or Closed |

## Derived tables (DuckDB)

| Table | Grain | Purpose |
|---|---|---|
| params | one row | The run date (`as_of`) every query reads |
| dq_results | market x check | Data-quality outcome with failing row counts |
| inv_clean, actuals_clean, forecast_clean, po_clean, sp_clean | as raw | Rows that passed hard rules |
| kpi_accuracy_sku | SKU | WAPE and bias over the last 8 complete weeks |
| proj | SKU x week | Projected end-of-week balance for 8 weeks |
| late_po | open PO | Open POs past their promised date |
| kpi_sku | SKU | Cover, stockout risk, accuracy, late POs, excess value |
| kpi_otif_supplier | market x supplier | OTIF over the trailing 26 weeks |
| kpi_market | market | The market scorecard |
| exceptions_rules, exceptions | exception | Rule-based and ML-based exceptions |
| ml_benchmark, ml_forecast | market / SKU-week | Baseline forecast scores and next 8 weeks |
| actions | action | The action tracker (owner role, due date, status, overdue, escalation) |
