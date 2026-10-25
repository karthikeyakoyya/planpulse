"""Baseline forecast (scikit-learn) and Isolation Forest for planning anomalies.

The baseline forecast is a benchmark, not a replacement for the planning system. It is scored
one-week-ahead on a holdout against the system forecast and two naive methods, and the result is
reported as it comes out, including when the system forecast wins.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, IsolationForest
from sklearn.preprocessing import StandardScaler

from . import config as C

LAGS = [1, 2, 3, 4]


def _wape(a, f):
    a, f = np.asarray(a, float), np.asarray(f, float)
    return float(np.abs(f - a).sum() / max(a.sum(), 1e-9))


def _features(wide: pd.DataFrame, scale: pd.Series) -> pd.DataFrame:
    """wide: index (market, sku), columns = week_start ascending. scale: per-SKU level used to normalise.
    Returns long frame with lag features."""
    norm = wide.div(scale, axis=0)
    weeks = list(norm.columns)
    rows = []
    for j in range(max(LAGS), len(weeks)):
        d = {f"lag{l}": norm.iloc[:, j - l].values for l in LAGS}
        d["roll8"] = norm.iloc[:, max(0, j - 8):j].mean(axis=1).values
        woy = pd.Timestamp(weeks[j]).isocalendar().week
        d["sin"], d["cos"] = np.sin(2 * np.pi * woy / 52), np.cos(2 * np.pi * woy / 52)
        d["y"] = norm.iloc[:, j].values
        d["week_start"] = weeks[j]
        d["market"] = wide.index.get_level_values(0)
        d["sku"] = wide.index.get_level_values(1)
        d["scale"] = scale.values
        rows.append(pd.DataFrame(d))
    return pd.concat(rows, ignore_index=True)


FEATS = [f"lag{l}" for l in LAGS] + ["roll8", "sin", "cos"]


def baseline_forecast(con, holdout_weeks: int = C.ACCURACY_WEEKS, seed: int = 42):
    """Returns (benchmark_df, next_weeks_df). Trains on all weeks before the holdout."""
    act = con.execute("SELECT market, sku, week_start, units FROM actuals_clean").df()
    fc = con.execute("SELECT market, sku, week_start, forecast_units FROM forecast_clean").df()
    wide = act.pivot_table(index=["market", "sku"], columns="week_start", values="units", aggfunc="sum").sort_index(axis=1)
    wide = wide.apply(lambda r: r.fillna(r.mean()), axis=1)  # fill the rare quarantined row with the SKU mean
    # SKU scale comes from the training weeks only, so the holdout never leaks into the model
    scale_train = wide.iloc[:, :-holdout_weeks].mean(axis=1).clip(lower=1.0)
    long = _features(wide, scale_train)
    weeks = sorted(long.week_start.unique())
    hold = weeks[-holdout_weeks:]
    train, test = long[~long.week_start.isin(hold)], long[long.week_start.isin(hold)].copy()
    model = GradientBoostingRegressor(n_estimators=150, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=seed)
    model.fit(train[FEATS], train["y"])
    test["ml"] = np.maximum(0, model.predict(test[FEATS])) * test["scale"]
    test["actual"] = test["y"] * test["scale"]
    test["naive"] = test["lag1"] * test["scale"]
    test["ma4"] = test[[f"lag{l}" for l in LAGS]].mean(axis=1) * test["scale"]
    test = test.merge(fc, on=["market", "sku", "week_start"], how="inner")
    bench = []
    for m, g in list(test.groupby("market")) + [("ALL", test)]:
        bench.append(dict(market=m, rows=len(g), wape_system=_wape(g.actual, g.forecast_units), wape_ml=_wape(g.actual, g.ml),
                          wape_naive=_wape(g.actual, g.naive), wape_ma4=_wape(g.actual, g.ma4)))
    bench = pd.DataFrame(bench)

    # refit on everything and roll forward recursively
    scale = wide.mean(axis=1).clip(lower=1.0)
    long = _features(wide, scale)
    model.fit(long[FEATS], long["y"])
    norm = wide.div(scale, axis=0)
    last = pd.Timestamp(norm.columns[-1])
    hist = {k: list(v) for k, v in norm.T.items()}
    out = []
    for step in range(1, C.HORIZON_WEEKS + 1):
        wk = (last + pd.Timedelta(weeks=step)).date()
        woy = pd.Timestamp(wk).isocalendar().week
        X = pd.DataFrame({f"lag{l}": [hist[k][-l] for k in hist] for l in LAGS})
        X["roll8"] = [np.mean(hist[k][-8:]) for k in hist]
        X["sin"], X["cos"] = np.sin(2 * np.pi * woy / 52), np.cos(2 * np.pi * woy / 52)
        pred = np.maximum(0, model.predict(X[FEATS]))
        for (k, p) in zip(hist, pred):
            hist[k].append(float(p))
            out.append((k[0], k[1], wk, float(p * scale.loc[k])))
    nxt = pd.DataFrame(out, columns=["market", "sku", "week_start", "ml_forecast_units"])
    return bench, nxt


def divergence(con, nxt: pd.DataFrame) -> pd.DataFrame:
    """System forecast vs ML baseline over the next 4 weeks; top 3 per market above threshold."""
    nxt = nxt.copy()
    nxt["week_start"] = pd.to_datetime(nxt["week_start"])
    sys_ = con.execute("""SELECT market, sku, week_start, forecast_units FROM forecast_clean
        WHERE week_start >= (SELECT as_of FROM params) AND week_start < (SELECT as_of FROM params) + 28""").df()
    sys_["week_start"] = pd.to_datetime(sys_["week_start"])
    m = sys_.merge(nxt, on=["market", "sku", "week_start"])
    g = m.groupby(["market", "sku"], as_index=False).agg(system=("forecast_units", "sum"), ml=("ml_forecast_units", "sum"))
    g["gap_pct"] = (g.system - g.ml) / g.ml.clip(lower=1)
    g["gap_units"] = (g.system - g.ml).abs()
    g = g[(g.gap_pct.abs() > C.DIVERGENCE_THRESHOLD) & (g.system + g.ml > 300)]
    return g.sort_values("gap_units", ascending=False).groupby("market").head(3).reset_index(drop=True)


ANOM_FEATURES = ["wape", "bias", "log_cover", "cover_vs_lt", "max_days_late", "supply_gap", "fcst_vs_recent"]


def anomalies(con, seed: int = 42) -> pd.DataFrame:
    df = con.execute("""
      SELECT k.market, k.sku, k.wape, k.bias, k.days_of_cover, k.lead_time_days, k.max_days_late,
             k.receipts_8w, k.demand_8w, k.avg_weekly_fcst_4w,
             (SELECT AVG(units) FROM actuals_clean a WHERE a.market = k.market AND a.sku = k.sku
                AND a.week_start >= (SELECT as_of FROM params) - 28) AS recent_actual
      FROM kpi_sku k""").df()
    df["log_cover"] = np.log1p(df.days_of_cover.fillna(df.days_of_cover.median()))
    df["cover_vs_lt"] = df.days_of_cover.fillna(df.days_of_cover.median()) / df.lead_time_days
    df["supply_gap"] = (df.receipts_8w - df.demand_8w) / df.demand_8w.clip(lower=1)
    df["fcst_vs_recent"] = df.avg_weekly_fcst_4w / df.recent_actual.clip(lower=1)
    X = df[ANOM_FEATURES].fillna(0).clip(-1e6, 1e6)
    Z = StandardScaler().fit_transform(X)
    iso = IsolationForest(n_estimators=300, contamination=C.ANOMALY_CONTAMINATION, random_state=seed).fit(Z)
    df["anomaly"] = iso.predict(Z) == -1
    df["score"] = -iso.score_samples(Z)
    top = np.abs(Z).argmax(axis=1)
    df["driver"] = [ANOM_FEATURES[i] for i in top]
    df["driver_z"] = [Z[r, i] for r, i in enumerate(top)]
    return df
