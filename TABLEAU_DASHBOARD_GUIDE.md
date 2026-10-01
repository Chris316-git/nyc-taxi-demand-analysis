# NYC Yellow Taxi — Tableau Public Dashboard Build Guide

Three interactive dashboards built from `dashboard_data/*.csv`. Tableau Public (free) works with CSV, so no database is needed.

## 0. Prep

1. In the project root run `python export_tableau_data.py`. It reproduces notebook 04 and 05 and writes the congestion and forecast CSVs to `dashboard_data/`. The demand CSVs from notebook 03 are already there.
2. Check the console: baseline WAPE should print about **13.62%**, model WAPE about **9.93%**, and the test set should be **1,344** rows. These match your README.
3. Install Tableau Public Desktop (public.tableau.com/app/discover → Download). Publishing needs a free account.

**Data sources** (each CSV is its own source — do not join them):

| Page | Files |
|---|---|
| 1 Demand | `hourly_demand`, `weekday_weekend`, `zone_summary`, `borough_summary`, `borough_hourly_profile`, `kpi_summary` |
| 2 Congestion | `congestion_summary`, `congestion_daily_fee_exposure`, `congestion_weekday_yoy`, `congestion_zone_yoy`, `congestion_daily_trips_yoy` |
| 3 Forecast | `forecast_metrics`, `forecast_daily_history`, `forecast_test_results_long`, `forecast_error_by_hour`, `forecast_error_by_day`, `forecast_feature_importance` |

Connect: **Connect → Text file**. Set `pickup_date`, `date`, `timestamp` to Date / Date & Time in the data pane. Set `PULocationID` and `pickup_hour`/`hour` to Dimension (right-click → Convert to Dimension).

## 1. Dashboard 1 — Demand Patterns (Jan 2025)

| Sheet | Build | Notes |
|---|---|---|
| KPI tiles | `kpi_summary`: drag each measure to Text | Peak hour 18:00 · 8,636/day · Midtown Center · top-10 share 37.6% · Manhattan 89.1% |
| Hourly demand | `hourly_demand`: Columns `pickup_hour`, Rows `avg_pickups_per_day` → Bar | Colour by the same measure (sequential); highlight 18:00 |
| Weekday vs weekend | `weekday_weekend`: Columns `pickup_hour`, Rows `avg_pickups`, Color `day_type` → Line | Two lines; peak 18:00 for both |
| Top zones | `zone_summary`: Rows `zone_label`, Columns `trip_count` → Bar; filter Top 15 by `trip_count` | Color by `pickup_borough` |
| Borough hour heatmap | `borough_hourly_profile`: Columns `pickup_hour` (discrete), Rows `pickup_borough`, Color `borough_hourly_share_pct` → Heatmap | Share of each borough's own pickups per hour |
| Borough share | `borough_summary`: Rows `pickup_borough`, Columns `trip_share_pct` → Bar | Manhattan 89.1% |

**Interactions:** Use *Dashboard → Actions → Add Action → Filter* with the borough bar as source and the top zones and heatmap as targets (*Select*, *Exclude all values* when cleared). Add a visible `day_type` quick filter on the weekday/weekend sheet. Add a Top-N parameter for the zone chart: Create Parameter `Top N` (int, 5–30, default 15) and use *Top → By field → Top [Top N]* on the zone filter.

## 2. Dashboard 2 — Congestion Pricing (descriptive)

**Fields to create** (Analysis → Create Calculated Field):

```
// congestion_zone_yoy
Zone Change Label   = IF [direction]="Increase" THEN "Up" ELSE "Down" END
Fee Exposure Band   = IF [fee_exposure_pct] >= 50 THEN "High (50%+)"
                      ELSEIF [fee_exposure_pct] >= 10 THEN "Medium"
                      ELSE "Low (<10%)" END
```

| Sheet | Build | Notes |
|---|---|---|
| KPI tiles | `congestion_summary` | YoY +17.2% · 64.7% fee exposure · correlation −0.272 · +190.8% / −19.5% |
| Daily fee exposure | `congestion_daily_fee_exposure`: Columns `pickup_date` (Day, continuous), Rows `fee_exposure_pct` → Line | First fee records on 2025-01-04/05; add reference line at 64.7% |
| Daily trips YoY | `congestion_daily_trips_yoy`: Columns `day_of_month`, Rows `trip_count`, Color `year` → Line | Lets viewers compare the same day of month |
| Weekday YoY | `congestion_weekday_yoy`: Columns `weekday` (sort by `weekday_num`), Rows `avg_daily_trips`, Color `year` → Bar side-by-side | Add `change_pct` as a label |
| Zone YoY | `congestion_zone_yoy`: Rows `zone_label`, Columns `change_pct`; filter `is_stable_zone` = True; Top 10 + Bottom 10 | Colour by `direction` |
| Scatter | Columns `fee_exposure_pct`, Rows `change_pct`, Detail `zone_label`, Color `pickup_borough`, Size `trips_2025`; filter `is_stable_zone` = True; add Trend Line | Hover tooltip shows zone and borough |

**Interactions:** Filter actions from the scatter to the zone bar, plus a borough quick filter applied to all sheets on this page (*Apply to Worksheets → Selected Worksheets*).

**Required caption (keep your README framing):** "Descriptive comparison of January 2024 vs January 2025. This is not a causal estimate; weather, holidays, taxi supply, transit changes and other factors are not controlled."

## 3. Dashboard 3 — 24-Hour-Ahead Forecast

| Sheet | Build | Notes |
|---|---|---|
| Metrics | `forecast_metrics`: Rows `model`, Text `MAE`, `RMSE`, `WAPE_pct` | Baseline 13.62% vs model 9.93% |
| History | `forecast_daily_history`: Columns `date`, Rows `rolling_7d_avg` → Line | Add a reference band for the 8-week test window starting 2026-06-06 |
| Actual vs forecast | `forecast_test_results_long`: Columns `timestamp` (exact), Rows `value`, Color `series` → Line | Add quick filters: `date` range and `day_type` |
| Error by hour | `forecast_error_by_hour`: Columns `hour`, Rows `MAE`, Color `model` → Bar | Highest error around 23:00 |
| Error by weekday | `forecast_error_by_day`: Columns `weekday` (sort by `weekday_num`), Rows `MAE`, Color `model` | Highest on Saturday |
| Importance | `forecast_feature_importance`: Rows `feature` (sort by `importance`), Columns `importance` | Top feature `lag_168` |

**Interactions:** Make the error-by-hour bar a filter action on the actual-vs-forecast line (click an hour to see only those target hours). Add a `model` quick filter, set to *Single value (list)* with default "Gradient Boosting", on the error charts.

**Required caption:** Single 8-week chronological holdout; no weather, events or taxi-supply features.

## 4. Assemble and publish

1. **New Dashboard** → Size: *Automatic* for the web, or *Fixed 1200×800* if layout shifts.
2. Layout: tiles across the top (Horizontal container), main charts in the middle, filters on the right.
3. Add a small navigation row to link the three dashboards: Objects → *Navigation* button, one per page.
4. Consistent colours: use one categorical palette for borough/model and one sequential palette for volume.
5. **File → Save to Tableau Public As…** → sign in. Tick *Show sheets as tabs* in the dashboard settings.
6. Copy the public link into the GitHub README: `[Interactive dashboard](your-link)` and add a screenshot.

## 5. Known limits

- The data are aggregated CSVs, so Tableau Public's 15M-row cap is not an issue.
- No map: Tableau cannot geocode NYC taxi-zone IDs. A map would need the TLC taxi-zone shapefile (a spatial file source) joined on `PULocationID` — an optional extension.
- Interactive filters on Dashboard 1 only cover January 2025, since the demand notebook is built on that month.
