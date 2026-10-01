"""
Export Tableau-ready CSVs for the NYC Yellow Taxi project.

Reproduces the cleaning / modelling logic of notebooks 04 (congestion) and
05 (forecasting) exactly, and writes small aggregated CSVs to dashboard_data/.
The demand CSVs from notebook 03 already exist in dashboard_data/.

Run from the project root (the folder containing data/ and notebook/):

    python export_tableau_data.py

Needs: pandas, numpy, pyarrow, scikit-learn  (all already in requirements.txt).
Inputs (all already in your project):
    data/raw/yellow_tripdata_2024-01.parquet
    data/raw/yellow_tripdata_2025-01.parquet
    data/raw/taxi_zone_lookup.csv
    data/processed/citywide_hourly_2024_01_to_2026_07.parquet
    data/processed/forecast_monthly_qc_2024_01_to_2026_07.csv
"""
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance
from sklearn.metrics import mean_absolute_error, mean_squared_error

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
OUT = ROOT / "dashboard_data"
OUT.mkdir(exist_ok=True)

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def save(df, name):
    df.to_csv(OUT / name, index=False)
    print(f"  wrote {name:<42s} {len(df):>7,d} rows")


# ---------------------------------------------------------------- congestion
def prepare_january(year, zones):
    """Same rules as notebook 04 `prepare_january_sample`."""
    path = RAW / f"yellow_tripdata_{year}-01.parquet"
    cols = ["tpep_pickup_datetime", "tpep_dropoff_datetime", "PULocationID"]
    import pyarrow.parquet as pq

    if "cbd_congestion_fee" in pq.ParquetFile(path).schema.names:
        cols.append("cbd_congestion_fee")
    df = pd.read_parquet(path, columns=cols)
    raw_trips = len(df)

    dur = (df["tpep_dropoff_datetime"] - df["tpep_pickup_datetime"]).dt.total_seconds() / 60
    mask = (
        df["tpep_pickup_datetime"].ge(pd.Timestamp(f"{year}-01-01"))
        & df["tpep_pickup_datetime"].lt(pd.Timestamp(f"{year}-02-01"))
        & dur.gt(0)
        & dur.le(360)
    )
    city = df.loc[mask].copy()
    city["pickup_date"] = city["tpep_pickup_datetime"].dt.floor("D")

    pz = zones[["LocationID", "Borough", "Zone"]].rename(
        columns={"LocationID": "PULocationID", "Borough": "pickup_borough", "Zone": "pickup_zone"}
    )
    zone_sample = city.merge(pz, on="PULocationID", how="left", validate="m:1")
    zone_sample = zone_sample.loc[~zone_sample["PULocationID"].isin([264, 265])].copy()
    return city, zone_sample, raw_trips


def export_congestion():
    print("Congestion analysis (notebook 04)")
    zones = pd.read_csv(RAW / "taxi_zone_lookup.csv")
    city24, zone24, raw24 = prepare_january(2024, zones)
    city25, zone25, raw25 = prepare_january(2025, zones)

    # daily fee exposure (2025)
    city25["fee_applied"] = city25["cbd_congestion_fee"].fillna(0) > 0
    daily = (
        city25.groupby("pickup_date")
        .agg(total_trips=("fee_applied", "size"), fee_positive_trips=("fee_applied", "sum"))
        .reset_index()
    )
    daily["fee_exposure_pct"] = daily["fee_positive_trips"] / daily["total_trips"] * 100
    daily["weekday"] = daily["pickup_date"].dt.day_name()
    daily["day_type"] = np.where(daily["pickup_date"].dt.dayofweek >= 5, "Weekend", "Weekday")
    save(daily.assign(pickup_date=daily["pickup_date"].dt.date), "congestion_daily_fee_exposure.csv")

    # fee value distribution
    fee_dist = (
        city25["cbd_congestion_fee"].value_counts(dropna=False).sort_index()
        .rename("trip_count").reset_index().rename(columns={"cbd_congestion_fee": "fee_value"})
    )
    save(fee_dist, "congestion_fee_distribution.csv")

    # daily trips both years, aligned by day of month (for YoY line chart)
    rows = []
    for yr, c in [(2024, city24), (2025, city25)]:
        d = c.groupby("pickup_date").size().rename("trip_count").reset_index()
        d["year"] = yr
        d["day_of_month"] = d["pickup_date"].dt.day
        d["weekday"] = d["pickup_date"].dt.day_name()
        d["weekday_num"] = d["pickup_date"].dt.dayofweek + 1
        d["pickup_date"] = d["pickup_date"].dt.date
        rows.append(d)
    daily_both = pd.concat(rows, ignore_index=True)
    save(daily_both, "congestion_daily_trips_yoy.csv")

    # weekday average, long format (Tableau-friendly) + change pct
    wk = daily_both.groupby(["year", "weekday", "weekday_num"])["trip_count"].mean().rename("avg_daily_trips").reset_index()
    piv = wk.pivot(index="weekday", columns="year", values="avg_daily_trips")
    wk["change_pct"] = wk["weekday"].map((piv[2025] - piv[2024]) / piv[2024] * 100)
    save(wk.sort_values(["weekday_num", "year"]), "congestion_weekday_yoy.csv")

    # zone YoY + fee exposure
    def zc(df, yr):
        return (
            df.groupby(["PULocationID", "pickup_borough", "pickup_zone"])
            .size().rename(f"trips_{yr}").reset_index()
        )

    z = zc(zone24, 2024).merge(zc(zone25, 2025), on=["PULocationID", "pickup_borough", "pickup_zone"], how="outer")
    z[["trips_2024", "trips_2025"]] = z[["trips_2024", "trips_2025"]].fillna(0)
    z["trip_change"] = z["trips_2025"] - z["trips_2024"]
    z["change_pct"] = np.where(z["trips_2024"] > 0, z["trip_change"] / z["trips_2024"] * 100, np.nan)
    z["is_stable_zone"] = (z["trips_2024"] >= 1000) & (z["trips_2025"] >= 1000)

    zone25 = zone25.copy()
    zone25["fee_applied"] = zone25["cbd_congestion_fee"].fillna(0) > 0
    fe = (
        zone25.groupby("PULocationID")
        .agg(total_trips_2025=("fee_applied", "size"), fee_positive_trips=("fee_applied", "sum"))
        .reset_index()
    )
    fe["fee_exposure_pct"] = fe["fee_positive_trips"] / fe["total_trips_2025"] * 100
    z = z.merge(fe, on="PULocationID", how="left")
    z["zone_label"] = z["pickup_zone"] + " (" + z["pickup_borough"] + ")"
    z["direction"] = np.where(z["trip_change"] >= 0, "Increase", "Decrease")
    # rank among stable zones (1 = largest increase)
    z["stable_rank_change"] = z["change_pct"].where(z["is_stable_zone"]).rank(ascending=False, method="first")
    save(z.sort_values("trips_2025", ascending=False), "congestion_zone_yoy.csv")

    # summary
    stable = z[z["is_stable_zone"]]
    corr = stable[["fee_exposure_pct", "change_pct"]].dropna().corr().iloc[0, 1]
    inc = stable.sort_values("change_pct", ascending=False).iloc[0]
    dec = stable.sort_values("change_pct", ascending=True).iloc[0]
    summ = pd.DataFrame(
        [
            {
                "trips_jan_2024": len(city24),
                "trips_jan_2025": len(city25),
                "yoy_change_pct": (len(city25) - len(city24)) / len(city24) * 100,
                "overall_fee_exposure_pct": city25["fee_applied"].mean() * 100,
                "first_fee_date": daily.loc[daily["fee_positive_trips"] > 0, "pickup_date"].min().date(),
                "max_daily_exposure_pct": daily["fee_exposure_pct"].max(),
                "max_exposure_date": daily.loc[daily["fee_exposure_pct"].idxmax(), "pickup_date"].date(),
                "largest_increase_zone": inc["zone_label"],
                "largest_increase_pct": inc["change_pct"],
                "largest_decrease_zone": dec["zone_label"],
                "largest_decrease_pct": dec["change_pct"],
                "fee_vs_change_correlation": corr,
                "raw_trips_2024": raw24,
                "raw_trips_2025": raw25,
            }
        ]
    )
    save(summ, "congestion_summary.csv")


# ------------------------------------------------------------------ forecast
def wape(y, p):
    return np.abs(y - p).sum() / np.abs(y).sum() * 100


def export_forecast():
    print("Forecasting (notebook 05)")
    hourly = pd.read_parquet(PROC / "citywide_hourly_2024_01_to_2026_07.parquet")

    # --- history (daily + 7-day rolling) for the trend chart
    daily = hourly.set_index("pickup_hour_ts")["trip_count"].resample("D").sum()
    hist = pd.DataFrame(
        {"date": daily.index.date, "daily_trips": daily.values, "rolling_7d_avg": daily.rolling(7).mean().values}
    )
    hist["weekday"] = pd.to_datetime(hist["date"]).dt.day_name()
    save(hist, "forecast_daily_history.csv")

    # --- features (identical to notebook)
    m = hourly.copy()
    ts = m["pickup_hour_ts"]
    m["year"], m["month"], m["hour"], m["day_of_week"] = ts.dt.year, ts.dt.month, ts.dt.hour, ts.dt.dayofweek
    m["is_weekend"] = (m["day_of_week"] >= 5).astype(int)
    for k in (24, 48, 168):
        m[f"lag_{k}"] = m["trip_count"].shift(k)
    known = m["trip_count"].shift(24)
    m["rolling_mean_24h"] = known.rolling(24).mean()
    m["rolling_mean_168h"] = known.rolling(168).mean()
    m["rolling_std_168h"] = known.rolling(168).std()
    feats = ["year", "month", "hour", "day_of_week", "is_weekend", "lag_24", "lag_48", "lag_168",
             "rolling_mean_24h", "rolling_mean_168h", "rolling_std_168h"]
    m = m.dropna(subset=feats + ["trip_count"]).reset_index(drop=True)

    test_hours = 8 * 7 * 24
    split = len(m) - test_hours
    train, test = m.iloc[:split], m.iloc[split:]
    print(f"  train {len(train):,} rows | test {len(test):,} rows")

    base = test["lag_168"].to_numpy()
    model = HistGradientBoostingRegressor(
        learning_rate=0.05, max_iter=250, max_leaf_nodes=31,
        l2_regularization=1.0, early_stopping=False, random_state=42,
    )
    model.fit(train[feats], train["trip_count"])
    pred = np.clip(model.predict(test[feats]), 0, None)
    y = test["trip_count"].to_numpy()

    # --- metrics
    def met(name, p):
        return {"model": name, "MAE": mean_absolute_error(y, p),
                "RMSE": float(np.sqrt(mean_squared_error(y, p))), "WAPE_pct": wape(y, p)}

    metrics = pd.DataFrame([met("Seasonal Naive (lag 168)", base), met("HistGradientBoosting", pred)])
    metrics["mae_improvement_vs_baseline_pct"] = (metrics.loc[0, "MAE"] - metrics["MAE"]) / metrics.loc[0, "MAE"] * 100
    save(metrics, "forecast_metrics.csv")

    # --- test results: wide + long
    res = pd.DataFrame({"timestamp": test["pickup_hour_ts"].to_numpy(), "actual": y,
                        "baseline": base, "gradient_boosting": pred})
    res["date"] = res["timestamp"].dt.date
    res["hour"] = res["timestamp"].dt.hour
    res["weekday"] = res["timestamp"].dt.day_name()
    res["weekday_num"] = res["timestamp"].dt.dayofweek + 1
    res["day_type"] = np.where(res["timestamp"].dt.dayofweek >= 5, "Weekend", "Weekday")
    res["baseline_abs_error"] = (res["actual"] - res["baseline"]).abs()
    res["model_abs_error"] = (res["actual"] - res["gradient_boosting"]).abs()
    res["model_error"] = res["gradient_boosting"] - res["actual"]  # signed (over/under-forecast)
    save(res, "forecast_test_results.csv")

    long = pd.concat([
        res[["timestamp", "date", "hour", "weekday", "weekday_num", "day_type"]].assign(series="Actual", value=res["actual"]),
        res[["timestamp", "date", "hour", "weekday", "weekday_num", "day_type"]].assign(series="Seasonal Naive (lag 168)", value=res["baseline"]),
        res[["timestamp", "date", "hour", "weekday", "weekday_num", "day_type"]].assign(series="Gradient Boosting", value=res["gradient_boosting"]),
    ], ignore_index=True)
    save(long, "forecast_test_results_long.csv")

    # --- error by hour / weekday (both models, long format)
    eh = res.groupby("hour")[["baseline_abs_error", "model_abs_error"]].mean().reset_index()
    eh = eh.melt("hour", var_name="model", value_name="MAE")
    eh["model"] = eh["model"].map({"baseline_abs_error": "Seasonal Naive (lag 168)", "model_abs_error": "Gradient Boosting"})
    save(eh, "forecast_error_by_hour.csv")

    ed = res.groupby(["weekday_num", "weekday"])[["baseline_abs_error", "model_abs_error"]].mean().reset_index()
    ed = ed.melt(["weekday_num", "weekday"], var_name="model", value_name="MAE")
    ed["model"] = ed["model"].map({"baseline_abs_error": "Seasonal Naive (lag 168)", "model_abs_error": "Gradient Boosting"})
    save(ed, "forecast_error_by_day.csv")

    # --- permutation importance (same settings as notebook)
    imp = permutation_importance(model, test[feats], test["trip_count"],
                                 scoring="neg_mean_absolute_error", n_repeats=5, random_state=42)
    fi = pd.DataFrame({"feature": feats, "importance": imp.importances_mean,
                       "importance_std": imp.importances_std}).sort_values("importance", ascending=False)
    save(fi, "forecast_feature_importance.csv")

    # --- monthly QC (copy of notebook cache)
    save(pd.read_csv(PROC / "forecast_monthly_qc_2024_01_to_2026_07.csv"), "forecast_monthly_qc.csv")

    # sanity check vs. README numbers
    print(f"  baseline WAPE {metrics.loc[0,'WAPE_pct']:.2f}% | model WAPE {metrics.loc[1,'WAPE_pct']:.2f}% "
          f"(README: 13.62% / 9.93%)")


if __name__ == "__main__":
    export_congestion()
    export_forecast()
    print("Done. Files are in:", OUT)
