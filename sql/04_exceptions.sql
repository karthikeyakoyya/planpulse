-- Rule-based exceptions. ref = the thing the action is about (SKU, PO id, supplier).
CREATE OR REPLACE TABLE exceptions_rules AS
SELECT market, 'STOCKOUT_RISK' AS exc_type,
  CASE stockout_risk WHEN 'HIGH' THEN 'P1' ELSE 'P2' END AS severity,
  sku AS ref, sku, CAST(NULL AS VARCHAR) AS supplier, days_of_cover AS metric,
  'Projected stockout in week ' || (stockout_week + 1) || ' of 8 (lead time ' || lead_time_days || ' d, cover '
    || ROUND(days_of_cover, 0) || ' d)' AS detail
FROM kpi_sku WHERE stockout_risk IN ('HIGH', 'MEDIUM')
UNION ALL
SELECT market, 'BELOW_SAFETY', 'P2', sku, sku, NULL, on_hand * 1.0 / NULLIF(safety_stock, 0),
  'On hand ' || on_hand || ' is below safety stock ' || safety_stock
FROM kpi_sku WHERE safety_stock IS NOT NULL AND on_hand < safety_stock AND stockout_risk <> 'HIGH'
UNION ALL
SELECT market, 'EXCESS_STOCK', 'P3', sku, sku, NULL, excess_value,
  'Cover ' || ROUND(days_of_cover, 0) || ' d exceeds {{EXCESS}} d; excess value ' || ROUND(excess_value, 0)
FROM kpi_sku WHERE days_of_cover > {{EXCESS}}
UNION ALL
SELECT market, 'FORECAST_BIAS', 'P2', sku, sku, NULL, bias,
  'Bias ' || ROUND(bias * 100, 0) || '% over last {{ACC}} weeks (WAPE ' || ROUND(wape * 100, 0) || '%)'
FROM kpi_accuracy_sku WHERE ABS(bias) > {{BIAS}} AND actual_units >= {{BIAS_MIN}}
UNION ALL
SELECT l.market, 'LATE_PO',
  CASE WHEN l.days_late >= {{LATE_P1}} OR COALESCE(k.stockout_risk, '') = 'HIGH' THEN 'P1' ELSE 'P2' END,
  l.po_id, l.sku, l.supplier, l.days_late,
  'PO ' || l.po_id || ' is ' || l.days_late || ' days past promised date, open qty ' || l.open_qty
FROM late_po l LEFT JOIN kpi_sku k USING (market, sku)  -- LEFT: SKUs quarantined for bad stock data must still surface
UNION ALL
SELECT market, 'SUPPLIER_OTIF', 'P2', supplier, NULL, supplier, otif_pos * 1.0 / pos,
  'Supplier OTIF ' || ROUND(otif_pos * 100.0 / pos, 0) || '% over ' || pos || ' POs'
FROM kpi_otif_supplier WHERE pos >= 10 AND otif_pos * 1.0 / pos < 0.5;
