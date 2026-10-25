-- Supplier OTIF over the trailing window. Params: market (optional)
SELECT market, supplier, pos, ROUND(on_time * 100.0 / pos, 1) AS on_time_pct, ROUND(in_full * 100.0 / pos, 1) AS in_full_pct,
       ROUND(otif_pos * 100.0 / pos, 1) AS otif_pct
FROM kpi_otif_supplier WHERE ($market IS NULL OR market = $market) ORDER BY otif_pct;
