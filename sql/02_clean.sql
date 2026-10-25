-- Clean layer. Rows that fail a hard rule are quarantined (excluded here, counted in dq_quarantine).
CREATE OR REPLACE TABLE inv_clean AS
SELECT DISTINCT market, sku, category, snapshot_date, on_hand, safety_stock, lead_time_days, unit_cost
FROM raw_inventory WHERE on_hand >= 0;

CREATE OR REPLACE TABLE actuals_clean AS
SELECT market, sku, week_start, units FROM raw_sales WHERE units >= 0;

CREATE OR REPLACE TABLE forecast_clean AS
SELECT market, sku, week_start, forecast_units FROM raw_forecast WHERE forecast_units IS NOT NULL;

CREATE OR REPLACE TABLE po_clean AS
SELECT * FROM raw_po
WHERE sku IN (SELECT sku FROM raw_inventory) AND promised_date >= order_date AND ordered_qty > 0;

CREATE OR REPLACE TABLE sp_clean AS
SELECT * FROM raw_supply_plan WHERE sku IN (SELECT sku FROM raw_inventory);
