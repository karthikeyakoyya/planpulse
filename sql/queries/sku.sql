-- Everything the KPI layer knows about one SKU. Params: sku (required)
SELECT * FROM kpi_sku WHERE sku = $sku;
