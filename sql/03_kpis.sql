-- Forecast accuracy: last {{ACC}} complete weeks, system lag-1 forecast vs actuals. WAPE and bias.
CREATE OR REPLACE TABLE kpi_accuracy_sku AS
SELECT a.market, a.sku,
  SUM(a.units) AS actual_units,
  SUM(f.forecast_units) AS forecast_units,
  SUM(ABS(f.forecast_units - a.units)) AS abs_err,
  SUM(ABS(f.forecast_units - a.units)) / NULLIF(SUM(a.units), 0) AS wape,
  (SUM(f.forecast_units) - SUM(a.units)) / NULLIF(SUM(a.units), 0) AS bias
FROM actuals_clean a JOIN forecast_clean f USING (market, sku, week_start)
WHERE a.week_start >= (SELECT as_of FROM params) - 7 * {{ACC}} AND a.week_start < (SELECT as_of FROM params)
GROUP BY a.market, a.sku;

-- Receipts by week: open POs not yet past due (remaining qty) + planned orders not yet placed.
-- Past-due POs are NOT counted (arrival date is unreliable); they raise a LATE_PO exception instead.
CREATE OR REPLACE TABLE receipts_wk AS
SELECT market, sku, wk, SUM(qty) AS receipts FROM (
  SELECT market, sku, LEAST({{HORIZON}} - 1, (promised_date - (SELECT as_of FROM params)) // 7) AS wk,
         ordered_qty - received_qty AS qty
  FROM po_clean WHERE status = 'Open' AND promised_date >= (SELECT as_of FROM params)
  UNION ALL
  SELECT market, sku, (week_start - (SELECT as_of FROM params)) // 7 AS wk, planned_qty AS qty
  FROM sp_clean WHERE source = 'PLANNED' AND week_start >= (SELECT as_of FROM params)
) GROUP BY market, sku, wk;

CREATE OR REPLACE TABLE proj AS
SELECT i.market, i.sku, g.wk,
  COALESCE(f.forecast_units, 0) AS demand,
  COALESCE(r.receipts, 0) AS receipts,
  i.on_hand + SUM(COALESCE(r.receipts, 0) - COALESCE(f.forecast_units, 0))
      OVER (PARTITION BY i.market, i.sku ORDER BY g.wk) AS end_balance
FROM inv_clean i
CROSS JOIN (SELECT unnest(range(0, {{HORIZON}})) AS wk) g
LEFT JOIN forecast_clean f ON f.market = i.market AND f.sku = i.sku
     AND f.week_start = (SELECT as_of FROM params) + CAST(7 * g.wk AS INTEGER)
LEFT JOIN receipts_wk r ON r.market = i.market AND r.sku = i.sku AND r.wk = g.wk;

CREATE OR REPLACE TABLE late_po AS
SELECT market, po_id, sku, supplier, promised_date, ordered_qty - received_qty AS open_qty,
       (SELECT as_of FROM params) - promised_date AS days_late
FROM po_clean WHERE status = 'Open' AND promised_date < (SELECT as_of FROM params);

CREATE OR REPLACE TABLE kpi_sku AS
WITH d AS (
  SELECT market, sku, AVG(forecast_units) AS avg_weekly_fcst_4w FROM forecast_clean
  WHERE week_start >= (SELECT as_of FROM params) AND week_start < (SELECT as_of FROM params) + 28
  GROUP BY market, sku),
so AS (SELECT market, sku, MIN(wk) AS stockout_week FROM proj WHERE end_balance < 0 GROUP BY market, sku),
lp AS (SELECT market, sku, MAX(days_late) AS max_days_late, COUNT(*) AS late_pos FROM late_po GROUP BY market, sku),
sp AS (SELECT market, sku, SUM(receipts) AS receipts_8w, SUM(demand) AS demand_8w FROM proj GROUP BY market, sku)
SELECT i.market, i.sku, i.category, i.on_hand, i.safety_stock, i.lead_time_days, i.unit_cost,
  d.avg_weekly_fcst_4w,
  i.on_hand / NULLIF(d.avg_weekly_fcst_4w / 7.0, 0) AS days_of_cover,
  so.stockout_week,
  CASE WHEN so.stockout_week IS NULL THEN 'LOW'
       WHEN so.stockout_week * 7 < i.lead_time_days THEN 'HIGH' ELSE 'MEDIUM' END AS stockout_risk,
  a.actual_units, a.forecast_units AS forecast_units_8w, a.abs_err, a.wape, a.bias,
  COALESCE(lp.max_days_late, 0) AS max_days_late, COALESCE(lp.late_pos, 0) AS late_pos,
  sp.receipts_8w, sp.demand_8w,
  GREATEST(0, i.on_hand - {{EXCESS}} * d.avg_weekly_fcst_4w / 7.0) * i.unit_cost AS excess_value
FROM inv_clean i
LEFT JOIN d USING (market, sku) LEFT JOIN so USING (market, sku) LEFT JOIN lp USING (market, sku)
LEFT JOIN sp USING (market, sku) LEFT JOIN kpi_accuracy_sku a USING (market, sku);

CREATE OR REPLACE TABLE kpi_otif_supplier AS
SELECT market, supplier, COUNT(*) AS pos,
  SUM(CASE WHEN received_date <= promised_date THEN 1 ELSE 0 END) AS on_time,
  SUM(CASE WHEN received_qty >= {{TOL}} * ordered_qty THEN 1 ELSE 0 END) AS in_full,
  SUM(CASE WHEN received_date <= promised_date AND received_qty >= {{TOL}} * ordered_qty THEN 1 ELSE 0 END) AS otif_pos
FROM po_clean
WHERE status = 'Closed' AND received_date >= (SELECT as_of FROM params) - 7 * {{OTIF}}
GROUP BY market, supplier;

CREATE OR REPLACE TABLE kpi_market AS
WITH acc AS (
  SELECT market, SUM(abs_err) AS abs_err_sum, SUM(actual_units) AS actual_sum, SUM(forecast_units) AS forecast_sum
  FROM kpi_accuracy_sku GROUP BY market)
SELECT s.market,
  COUNT(*) AS skus,
  MAX(acc.abs_err_sum) / NULLIF(MAX(acc.actual_sum), 0) AS wape,
  (MAX(acc.forecast_sum) - MAX(acc.actual_sum)) / NULLIF(MAX(acc.actual_sum), 0) AS bias,
  AVG(s.days_of_cover) AS avg_days_cover,
  SUM(CASE WHEN s.stockout_risk = 'HIGH' THEN 1 ELSE 0 END) AS high_risk_skus,
  SUM(CASE WHEN s.stockout_risk = 'MEDIUM' THEN 1 ELSE 0 END) AS medium_risk_skus,
  SUM(CASE WHEN s.safety_stock IS NOT NULL AND s.on_hand < s.safety_stock THEN 1 ELSE 0 END) AS below_safety_skus,
  SUM(s.excess_value) AS excess_value,
  MAX(acc.abs_err_sum) AS abs_err_sum, MAX(acc.actual_sum) AS actual_sum, MAX(acc.forecast_sum) AS forecast_sum,
  SUM(s.days_of_cover) AS cover_sum, COUNT(s.days_of_cover) AS cover_n,
  (SELECT SUM(otif_pos) FROM kpi_otif_supplier o WHERE o.market = s.market) AS otif_pos_sum,
  (SELECT SUM(pos) FROM kpi_otif_supplier o WHERE o.market = s.market) AS otif_n,
  (SELECT COUNT(*) FROM late_po l WHERE l.market = s.market) AS late_pos,
  (SELECT SUM(otif_pos) * 1.0 / NULLIF(SUM(pos), 0) FROM kpi_otif_supplier o WHERE o.market = s.market) AS otif
FROM kpi_sku s LEFT JOIN acc ON acc.market = s.market
GROUP BY s.market;
