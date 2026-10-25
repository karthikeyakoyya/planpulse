-- Each block: "-- check: ID | severity | description", then a query returning (market, n_fail).
-- Severity maps to action priority: HIGH=P1, MEDIUM=P2, LOW=P3. Markets with zero failures may be omitted.

-- check: INV_DUP | MEDIUM | Duplicate (market, sku) rows in inventory extract
SELECT market, SUM(c - 1) AS n_fail
FROM (SELECT market, sku, COUNT(*) AS c FROM raw_inventory GROUP BY market, sku HAVING COUNT(*) > 1)
GROUP BY market;

-- check: INV_NEG_ONHAND | HIGH | Negative on-hand quantity in inventory extract
SELECT market, COUNT(*) AS n_fail FROM raw_inventory WHERE on_hand < 0 GROUP BY market;

-- check: INV_NULL_SS | MEDIUM | Missing safety stock value
SELECT market, COUNT(*) AS n_fail FROM raw_inventory WHERE safety_stock IS NULL GROUP BY market;

-- check: INV_STALE | HIGH | Inventory snapshot older than {{FRESH}} days at run date
SELECT market, COUNT(*) AS n_fail FROM raw_inventory
WHERE date_diff('day', snapshot_date, (SELECT as_of FROM params)) > {{FRESH}} GROUP BY market;

-- check: FC_NULL | MEDIUM | Forecast row with missing quantity
SELECT market, COUNT(*) AS n_fail FROM raw_forecast WHERE forecast_units IS NULL GROUP BY market;

-- check: FC_HORIZON_GAP | MEDIUM | SKU without forecast for every one of the next {{HORIZON}} weeks
SELECT market, COUNT(*) AS n_fail FROM (
  SELECT market, sku, COUNT(forecast_units) AS n FROM raw_forecast
  WHERE week_start >= (SELECT as_of FROM params) GROUP BY market, sku HAVING COUNT(forecast_units) < {{HORIZON}}
) GROUP BY market;

-- check: SALES_NEG | LOW | Negative units in sales actuals (returns not netted?)
SELECT market, COUNT(*) AS n_fail FROM raw_sales WHERE units < 0 GROUP BY market;

-- check: PO_DATE_ORDER | MEDIUM | PO promised date earlier than order date
SELECT market, COUNT(*) AS n_fail FROM raw_po WHERE promised_date < order_date GROUP BY market;

-- check: PO_ORPHAN | HIGH | PO references a SKU that is not in the inventory master
SELECT market, COUNT(*) AS n_fail FROM raw_po
WHERE sku NOT IN (SELECT sku FROM raw_inventory) GROUP BY market;

-- check: PO_QTY | LOW | PO with non-positive ordered quantity
SELECT market, COUNT(*) AS n_fail FROM raw_po WHERE ordered_qty <= 0 GROUP BY market;
