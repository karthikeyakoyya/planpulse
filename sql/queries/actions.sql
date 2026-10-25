-- Action tracker view. Params: market (optional), status (optional), overdue_only (true/false)
SELECT action_id, market, severity, exc_type, ref, owner_role, due_date, status, days_overdue, escalation_level
FROM actions
WHERE ($market IS NULL OR market = $market) AND ($status IS NULL OR status = $status)
  AND (NOT COALESCE($overdue_only, false) OR days_overdue > 0)
ORDER BY escalation_level DESC, days_overdue DESC, severity;
