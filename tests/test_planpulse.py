"""Tests use a tiny hand-built market (known answers) and the simulator (injected defects)."""
from datetime import date, timedelta

import pandas as pd
import pytest

from planpulse import actions as A
from planpulse import config as C
from planpulse import narrative, pipeline, queries, simulate

AS_OF = "2026-10-26"


def _weeks(start, n):
    return [(date.fromisoformat(start) + timedelta(weeks=k)).isoformat() for k in range(n)]


@pytest.fixture()
def tiny(tmp_path):
    d = tmp_path / "raw" / "t"
    d.mkdir(parents=True)
    hist = _weeks("2026-08-31", 8)           # the 8 complete weeks before AS_OF
    fut = _weeks(AS_OF, 8)
    pd.DataFrame([("T", "T-1", w, 100) for w in hist], columns=["market", "sku", "week_start", "units"]).to_csv(d / "sales_actuals.csv", index=False)
    pd.DataFrame([("T", "T-1", w, 110) for w in hist] + [("T", "T-1", w, 70) for w in fut],
                 columns=["market", "sku", "week_start", "forecast_units"]).to_csv(d / "forecast.csv", index=False)
    pd.DataFrame([("T", "T-1", "Devices", "2026-10-25", 140, 10, 7, 10.0)],
                 columns=["market", "sku", "category", "snapshot_date", "on_hand", "safety_stock", "lead_time_days", "unit_cost"]).to_csv(d / "inventory.csv", index=False)
    pd.DataFrame([("T", "T-1", fut[7], 0, "PLANNED")], columns=["market", "sku", "week_start", "planned_qty", "source"]).to_csv(d / "supply_plan.csv", index=False)
    pd.DataFrame([("PO1", "T", "T-1", "S1", "2026-08-01", "2026-09-01", 100, 100, "2026-09-01", "Closed"),
                  ("PO2", "T", "T-1", "S1", "2026-08-01", "2026-09-01", 100, 100, "2026-09-09", "Closed"),
                  ("PO3", "T", "T-1", "S1", "2026-09-01", "2026-10-20", 50, 0, None, "Open")],
                 columns=["po_id", "market", "sku", "supplier", "order_date", "promised_date", "ordered_qty", "received_qty", "received_date", "status"]).to_csv(d / "po.csv", index=False)
    con = pipeline.connect(":memory:")
    pipeline.build(con, tmp_path / "raw", AS_OF)
    return con


def test_wape_and_bias(tiny):
    r = tiny.execute("SELECT wape, bias FROM kpi_accuracy_sku").fetchone()
    assert r[0] == pytest.approx(0.10) and r[1] == pytest.approx(0.10)


def test_cover_and_stockout_projection(tiny):
    r = tiny.execute("SELECT days_of_cover, stockout_week, stockout_risk FROM kpi_sku").fetchone()
    assert r[0] == pytest.approx(14.0)
    assert r[1] == 2                      # 140 - 70 - 70 = 0 after week 1, negative in week 2
    assert r[2] == "MEDIUM"               # stockout (14 d) is after the 7 d lead time


def test_otif_and_late_po(tiny):
    o = tiny.execute("SELECT pos, on_time, otif_pos FROM kpi_otif_supplier").fetchone()
    assert o == (2, 1, 1)
    late = tiny.execute("SELECT po_id, days_late FROM late_po").fetchone()
    assert late == ("PO3", 6)


def test_past_due_po_not_counted_as_receipt(tiny):
    assert tiny.execute("SELECT COALESCE(SUM(receipts), 0) FROM proj").fetchone()[0] == 0


def test_dq_catches_injected_defects(tmp_path):
    inj = simulate.simulate(tmp_path / "raw", AS_OF)
    con = pipeline.connect(":memory:")
    dq = pipeline.build(con, tmp_path / "raw", AS_OF)
    got = {(r.market, r.check_id): r.n_fail for r in dq.itertuples()}
    for m, d in inj.items():
        assert got[(m, "INV_DUP")] == len(d["duplicate_inventory_rows"])
        assert got[(m, "INV_NEG_ONHAND")] == len(d["negative_on_hand"])
        assert got[(m, "INV_NULL_SS")] == len(d["null_safety_stock"])
        assert got[(m, "FC_NULL")] == d["null_forecast_rows"]
        assert got[(m, "PO_DATE_ORDER")] == len(d["po_promised_before_order"])
        assert got[(m, "PO_ORPHAN")] == len(d["orphan_po_sku"])
        assert got[(m, "SALES_NEG")] == d["negative_sales_rows"]
        assert (got[(m, "INV_STALE")] > 0) == ("stale_snapshot_days" in d)
    # quarantined rows must not reach KPI tables
    assert con.execute("SELECT COUNT(*) FROM inv_clean WHERE on_hand < 0").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM po_clean WHERE sku LIKE '%XXX%'").fetchone()[0] == 0


def _exc(rows):
    df = pd.DataFrame(rows, columns=["market", "exc_type", "severity", "ref", "detail"])
    df["key"] = df.market + "|" + df.exc_type + "|" + df.ref
    df["owner_role"] = "Supply Planner, " + df.market
    return df


def test_action_lifecycle_and_escalation():
    con = pipeline.connect(":memory:")
    e = _exc([("APAC", "STOCKOUT_RISK", "P1", "S1", "x"), ("APAC", "FORECAST_BIAS", "P2", "S2", "y")])
    a = A.sync_actions(con, e, "2026-10-19")
    assert list(a.action_id) == ["ACT-0001", "ACT-0002"]
    assert a.loc[0, "due_date"] == pd.Timestamp("2026-10-21") and a.loc[1, "due_date"] == pd.Timestamp("2026-10-24")
    # next week: P1 still flagged (id kept, now 5 days late, SLA 2 -> level 2); P2 gone -> verify
    a = A.sync_actions(con, e.iloc[[0]], "2026-10-26")
    p1, p2 = a.iloc[0], a.iloc[1]
    assert p1.action_id == "ACT-0001" and p1.days_overdue == 5 and p1.escalation_level == 2
    assert p2.status == "Resolved-Verify" and p2.escalation_level == 0
    # one day late within SLA -> level 1
    a = A.sync_actions(con, e.iloc[[0]], "2026-10-22")
    assert a.iloc[0].days_overdue == 1 and a.iloc[0].escalation_level == 1
    # closing clears overdue; a reappearance after close makes a NEW action
    A.update_action(con, "ACT-0001", "Closed", "done", "2026-10-22", "2026-10-22")
    a = A.sync_actions(con, e.iloc[[0]], "2026-10-29")
    assert (a.action_id == "ACT-0003").any()


def test_meeting_import(tmp_path):
    f = tmp_path / "m.md"
    f.write_text("- ACTION: Chase supplier | owner: Procurement Lead, APAC | due: 2026-11-02 | market: APAC\nnot an action\n")
    con = pipeline.connect(":memory:")
    assert A.import_meeting(con, f, "2026-10-26", "2026-10-26") == 1
    assert A.import_meeting(con, f, "2026-10-26", "2026-10-26") == 0     # idempotent
    row = A.load_actions(con).iloc[0]
    assert row.source == "meeting" and row.due_date == pd.Timestamp("2026-11-02")


def test_number_check_flags_invented_figures():
    facts = {"as_of": "2026-10-26", "markets": {"APAC": {"wape_pct": 16.0}}}
    assert narrative.numbers_not_in_facts("APAC WAPE was 16.0%", facts) == []
    assert narrative.numbers_not_in_facts("APAC WAPE was 42.5%", facts) == ["42.5"]


def test_query_layer_is_read_only(tiny):
    with pytest.raises(SystemExit):
        queries.read_only_sql("DROP TABLE kpi_sku", tiny)
    df = queries.run("cover", {"max_days": "30"}, con=tiny)
    assert len(df) == 1 and df.iloc[0].sku == "T-1"


def test_data_dictionary_covers_every_extract_column(tmp_path):
    simulate.simulate(tmp_path / "raw", AS_OF)
    doc = (C.ROOT / "docs" / "data_dictionary.md").read_text()
    cols = set()
    for f in (tmp_path / "raw" / "apac").glob("*.csv"):
        cols |= set(pd.read_csv(f, nrows=1).columns)
    missing = [c for c in cols if f"| {c} |" not in doc]
    assert not missing, f"undocumented columns: {missing}"


def test_every_late_po_becomes_an_exception(tmp_path):
    simulate.simulate(tmp_path / "raw", AS_OF)
    con = pipeline.connect(":memory:")
    pipeline.build(con, tmp_path / "raw", AS_OF)
    late = con.execute("SELECT COUNT(*) FROM late_po").fetchone()[0]
    exc = con.execute("SELECT COUNT(*) FROM exceptions_rules WHERE exc_type = 'LATE_PO'").fetchone()[0]
    assert late > 0 and late == exc


def test_market_accuracy_includes_skus_quarantined_for_stock_data(tmp_path):
    simulate.simulate(tmp_path / "raw", AS_OF)
    con = pipeline.connect(":memory:")
    pipeline.build(con, tmp_path / "raw", AS_OF)
    quarantined = con.execute("SELECT COUNT(DISTINCT sku) FROM raw_inventory WHERE on_hand < 0").fetchone()[0]
    assert quarantined > 0
    for market, wape in con.execute("SELECT market, wape FROM kpi_market").fetchall():
        a = pd.read_csv(tmp_path / "raw" / simulate.slug(market) / "sales_actuals.csv", parse_dates=["week_start"])
        f = pd.read_csv(tmp_path / "raw" / simulate.slug(market) / "forecast.csv", parse_dates=["week_start"])
        m = a[a.units >= 0].merge(f.dropna(), on=["market", "sku", "week_start"])
        m = m[(m.week_start >= pd.Timestamp(AS_OF) - pd.Timedelta(days=56)) & (m.week_start < pd.Timestamp(AS_OF))]
        expected = (m.forecast_units - m.units).abs().sum() / m.units.sum()
        assert wape == pytest.approx(expected)


def test_claude_draft_uses_client_and_falls_back(monkeypatch):
    """No live API in tests: a fake client checks the call shape, a failing one checks the template fallback."""
    import sys
    import types

    facts = {"as_of": AS_OF, "open_actions": 3, "overdue_actions": 1, "escalated_l2": 0,
             "markets": {"APAC": dict(wape_pct=16.0, bias_pct=1.0, avg_days_cover=40.0, high_stockout_risk_skus=2, late_pos=1,
                                      otif_pct=70.0, p1_exceptions=1, total_exceptions=4, top_p1=[])}}
    calls = []

    class FakeMessages:
        def create(self, **kw):
            calls.append(kw)
            block = types.SimpleNamespace(type="text", text="Simulated data. APAC WAPE was 16.0%.")
            return types.SimpleNamespace(content=[block])

    fake = types.SimpleNamespace(Anthropic=lambda api_key: types.SimpleNamespace(messages=FakeMessages()))
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    text = narrative.claude_draft(facts)
    assert text == "Simulated data. APAC WAPE was 16.0%."
    assert calls[0]["model"] == narrative.MODEL and "FACTS" in calls[0]["messages"][0]["content"]
    assert narrative.numbers_not_in_facts(text, facts) == []

    class Boom:
        def create(self, **kw):
            raise RuntimeError("network down")

    boom = types.SimpleNamespace(Anthropic=lambda api_key: types.SimpleNamespace(messages=Boom()))
    monkeypatch.setitem(sys.modules, "anthropic", boom)
    assert narrative.claude_draft(facts) is None          # caller then uses template_draft
    assert "Simulated data" in narrative.template_draft(facts)
