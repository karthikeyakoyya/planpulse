"""Generate fictional per-market extracts. Nothing here is real ISCP or company data.

A few defects are injected on purpose so the data-quality checks have something to find.
The list of injected defects is written to data/raw/_injected_defects.json and is used by tests.
"""
import json
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as C

CATEGORIES = ["Devices", "Accessories", "Network", "Storage"]
HIST_WEEKS = 52


def slug(market: str) -> str:
    return market.lower().replace(" ", "_").replace("-", "_")


def simulate(out_dir: Path = C.DATA_RAW, as_of: str = C.DEFAULT_AS_OF, seed: int = 42, ops_offset: int = 0) -> dict:
    """ops_offset changes only the operational state (stock on hand, POs, supply plan), not demand or master data.
    It exists so a second simulated week can exercise action carry-forward and auto-resolution."""
    rng = np.random.default_rng(seed)
    as_of_d = date.fromisoformat(as_of)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    hist = [as_of_d - timedelta(weeks=k) for k in range(HIST_WEEKS, 0, -1)]   # complete weeks
    future = [as_of_d + timedelta(weeks=k) for k in range(C.HORIZON_WEEKS)]
    defects = {}

    for idx, (market, cfg) in enumerate(C.MARKETS.items()):
        d = out_dir / slug(market)
        d.mkdir(exist_ok=True)
        n = cfg["skus"]
        skus = [f"{cfg['code']}-{CATEGORIES[i % 4][:3].upper()}-{i + 1:03d}" for i in range(n)]
        cats = [CATEGORIES[i % 4] for i in range(n)]
        base = rng.lognormal(mean=4.6, sigma=0.7, size=n)            # weekly units
        trend = rng.normal(0.0, 0.004, size=n)
        phase = rng.uniform(0, 2 * math.pi, size=n)
        season_amp = rng.uniform(0.05, 0.25, size=n)
        biased = set(rng.choice(n, size=max(2, n // 12), replace=False).tolist())
        sku_bias = np.where([i in biased for i in range(n)], rng.choice([-0.32, 0.32], size=n), rng.normal(0, 0.04, n))

        all_weeks = hist + future
        t = np.arange(len(all_weeks))
        mean = base[:, None] * (1 + trend[:, None] * t[None, :]) * (1 + season_amp[:, None] * np.sin(2 * math.pi * t[None, :] / 52 + phase[:, None]))
        mean = np.maximum(mean, 1.0)
        actual = np.maximum(0, rng.normal(mean, cfg["vol"] * mean)).round()
        fc = np.maximum(0, mean * (1 + sku_bias[:, None]) * (1 + rng.normal(0, 0.06, mean.shape))).round()

        rows_a, rows_f = [], []
        for i, s in enumerate(skus):
            for j, w in enumerate(all_weeks):
                if j < HIST_WEEKS:
                    rows_a.append((market, s, w.isoformat(), int(actual[i, j])))
                rows_f.append((market, s, w.isoformat(), int(fc[i, j])))
        sales = pd.DataFrame(rows_a, columns=["market", "sku", "week_start", "units"])
        fcst = pd.DataFrame(rows_f, columns=["market", "sku", "week_start", "forecast_units"])

        # master data and defect choices are stable week to week; operational state follows ops_offset
        rng = np.random.default_rng([seed, 7, idx])
        lt = rng.integers(cfg["lt"][0], cfg["lt"][1] + 1, size=n)
        sigma = cfg["vol"] * base
        safety = (1.65 * sigma * np.sqrt(lt / 7)).round()
        cost = rng.uniform(15, 900, size=n).round(2)
        reliab = rng.uniform(0.6, 0.97, size=cfg['suppliers'])
        defect_rng = np.random.default_rng([seed, 11, idx])
        rng = np.random.default_rng([seed, 99, ops_offset, idx])
        cover_weeks = rng.lognormal(mean=math.log(5), sigma=0.75, size=n)
        on_hand = (base * cover_weeks).round()
        snap = as_of_d - timedelta(days=1)
        inv = pd.DataFrame(dict(market=market, sku=skus, category=cats, snapshot_date=snap.isoformat(),
                                on_hand=on_hand.astype(int), safety_stock=safety.astype(int),
                                lead_time_days=lt, unit_cost=cost))

        # supply plan: weekly receipts. PO = backed by an open PO, PLANNED = planned order not yet placed
        sp_rows, po_rows = [], []
        sup = [f"SUP-{cfg['code']}-{k + 1:02d}" for k in range(cfg["suppliers"])]
        po_id = 1
        for i, s in enumerate(skus):
            # closed PO history (last 26 weeks)
            for _ in range(rng.integers(3, 7)):
                k = int(rng.integers(0, len(sup)))
                od = as_of_d - timedelta(days=int(rng.integers(40, 180)))
                promised = od + timedelta(days=int(lt[i]))
                q = int(max(20, base[i] * rng.uniform(2, 6)))
                on_time = rng.random() < reliab[k]
                full = rng.random() < (0.5 + reliab[k] / 2)
                recv = promised + timedelta(days=0 if on_time else int(rng.integers(2, 15)))
                if recv >= as_of_d:
                    recv = as_of_d - timedelta(days=1)
                po_rows.append((f"PO{po_id:06d}", market, s, sup[k], od.isoformat(), promised.isoformat(), q,
                                q if full else int(q * rng.uniform(0.6, 0.97)), recv.isoformat(), "Closed"))
                po_id += 1
            # open POs
            for _ in range(int(rng.integers(0, 3))):
                k = int(rng.integers(0, len(sup)))
                due_off = int(rng.integers(-12, 50))
                promised = as_of_d + timedelta(days=due_off)
                od = promised - timedelta(days=int(lt[i]))
                q = int(max(20, base[i] * rng.uniform(2, 6)))
                po_rows.append((f"PO{po_id:06d}", market, s, sup[k], od.isoformat(), promised.isoformat(), q, 0, None, "Open"))
                po_id += 1
                if due_off >= 0:
                    wk = min(C.HORIZON_WEEKS - 1, due_off // 7)
                    sp_rows.append((market, s, future[wk].isoformat(), q, "PO"))
            # planned receipts (cover most of the demand gap but not always)
            for wk in range(0, C.HORIZON_WEEKS, 2):
                if rng.random() < 0.55:
                    sp_rows.append((market, s, future[wk].isoformat(), int(base[i] * rng.uniform(1.5, 3.5)), "PLANNED"))
        sp = pd.DataFrame(sp_rows, columns=["market", "sku", "week_start", "planned_qty", "source"])
        po = pd.DataFrame(po_rows, columns=["po_id", "market", "sku", "supplier", "order_date", "promised_date",
                                            "ordered_qty", "received_qty", "received_date", "status"])

        # ---- injected defects (documented, deterministic) ----
        inj = {}
        dup_idx = defect_rng.choice(n, size=2, replace=False)
        inv = pd.concat([inv, inv.iloc[dup_idx]], ignore_index=True)
        inj["duplicate_inventory_rows"] = [skus[i] for i in dup_idx]
        neg = defect_rng.choice([i for i in range(n) if i not in dup_idx], size=2, replace=False)
        inv.loc[inv.sku.isin([skus[i] for i in neg]), "on_hand"] = -abs(int(defect_rng.integers(5, 60)))
        inj["negative_on_hand"] = [skus[i] for i in neg]
        nul = defect_rng.choice([i for i in range(n) if i not in dup_idx and i not in neg], size=2, replace=False)
        inv["safety_stock"] = inv["safety_stock"].astype("Int64")
        inv.loc[inv.sku.isin([skus[i] for i in nul]), "safety_stock"] = pd.NA
        inj["null_safety_stock"] = [skus[i] for i in nul]
        fn = defect_rng.choice(len(fcst), size=3, replace=False)
        fcst["forecast_units"] = fcst["forecast_units"].astype("Int64")
        fcst.loc[fn, "forecast_units"] = pd.NA
        inj["null_forecast_rows"] = int(len(fn))
        closed_idx = po.index[po.status == "Closed"][:2]
        po.loc[closed_idx, "promised_date"] = (pd.to_datetime(po.loc[closed_idx, "order_date"]) - pd.Timedelta(days=3)).dt.date.astype(str)
        inj["po_promised_before_order"] = po.loc[closed_idx, "po_id"].tolist()
        orphan = po.iloc[[-1, -2]].copy()
        orphan["po_id"] = [f"PO9{cfg['code']}01", f"PO9{cfg['code']}02"]
        orphan["sku"] = [f"{cfg['code']}-XXX-900", f"{cfg['code']}-XXX-901"]
        po = pd.concat([po, orphan], ignore_index=True)
        inj["orphan_po_sku"] = orphan["sku"].tolist()
        if market == "APAC":
            inv["snapshot_date"] = (as_of_d - timedelta(days=9)).isoformat()
            inj["stale_snapshot_days"] = 9
        sales.loc[sales.index[5], "units"] = -4
        inj["negative_sales_rows"] = 1
        defects[market] = inj

        sales.to_csv(d / "sales_actuals.csv", index=False)
        fcst.to_csv(d / "forecast.csv", index=False)
        inv.to_csv(d / "inventory.csv", index=False)
        sp.to_csv(d / "supply_plan.csv", index=False)
        po.to_csv(d / "po.csv", index=False)

    (out_dir / "_injected_defects.json").write_text(json.dumps(defects, indent=2))
    return defects
