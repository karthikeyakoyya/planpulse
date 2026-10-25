-- Largest excess inventory by value. Params: market (optional), top (default 10)
SELECT market, sku, ROUND(days_of_cover, 0) AS days_of_cover, ROUND(excess_value, 0) AS excess_value
FROM kpi_sku WHERE excess_value > 0 AND ($market IS NULL OR market = $market)
ORDER BY excess_value DESC LIMIT COALESCE($top, 10);
