-- Open POs past their promised date. Params: market (optional), supplier (optional)
SELECT market, po_id, sku, supplier, promised_date, open_qty, days_late
FROM late_po
WHERE ($market IS NULL OR market = $market) AND ($supplier IS NULL OR supplier = $supplier)
ORDER BY days_late DESC;
