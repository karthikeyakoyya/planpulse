-- SKUs with days of cover at or below a threshold. Params: market (optional), max_days (default 21)
SELECT market, sku, category, on_hand, safety_stock, lead_time_days, ROUND(days_of_cover, 1) AS days_of_cover, stockout_risk
FROM kpi_sku
WHERE ($market IS NULL OR market = $market) AND days_of_cover <= COALESCE($max_days, 21)
ORDER BY days_of_cover;
