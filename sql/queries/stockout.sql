-- SKUs projected to stock out within N weeks. Params: market (optional), weeks (default 4)
SELECT market, sku, stockout_week, lead_time_days, ROUND(days_of_cover, 1) AS days_of_cover, stockout_risk, late_pos
FROM kpi_sku
WHERE stockout_week IS NOT NULL AND stockout_week < COALESCE($weeks, 4) AND ($market IS NULL OR market = $market)
ORDER BY stockout_week, lead_time_days DESC;
