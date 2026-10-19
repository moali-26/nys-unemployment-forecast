# nys-unemployment-forecast

Can economic indicators and alternative data improve short-term forecasts of the New York State unemployment rate (FRED `NYUR`)?

## Data pipeline (Step 1)

### Running it

With the virtual environment active and `FRED_API_KEY` set in `.env` (see `.env.example`), run from the repo root:

```
python src/data/fetch_fred.py
python src/data/fetch_yfinance.py
python src/data/build_panel.py
python src/data/check_panel.py
```

The fetch scripts save untouched source data to `data/raw/`. `build_panel.py` converts everything to monthly and writes `data/processed/monthly_panel.csv`. `check_panel.py` runs sanity checks and saves a plot of every column to `data/processed/panel_plots.png`.

You don't need to rerun anything to use the data: the committed `monthly_panel.csv` is a frozen snapshot. Rerunning the fetch scripts pulls the latest data, and past values can change because FRED revises them.

**Data as of:** 2026-10-19.

### Panel format

- One row per month, `date` as `YYYY-MM-01`, from 1976-01 (the start of `NYUR`) to the last complete month.
- **Rows are dated by reference month, not release date.** The August unemployment rate is in the `2026-08-01` row even though it was published in September. In backtests, only use values that would have been published by the forecast date, or you will leak future information.
- **Levels only.** Compute growth rates, differences and lags in your own code.
- **Missing values are NaN and are never filled.** Series start at different dates, and the latest month is often missing for slower series.

### Columns

| Column | Source | How it becomes monthly |
|---|---|---|
| `ny_ur` | FRED `NYUR`, NY unemployment rate, SA. **Target.** | Monthly already |
| `ny_claims` | FRED `NYICLAIMS`, NY initial claims, NSA | Week containing the 12th (see below) |
| `ny_claims_avg` | FRED `NYICLAIMS` | Average of all weeks ending in the month; NaN if fewer than 4 weeks |
| `ny_claims_avg_sa` | `ny_claims_avg`, seasonally adjusted with STL | **Use this one for NY claims in models** |
| `ny_payrolls` | FRED `NYNA`, NY nonfarm employees, SA, thousands | Monthly already |
| `ny_coincident` | FRED `NYPHCI`, Philly Fed NY coincident index | Monthly already |
| `us_ur` | FRED `UNRATE`, US unemployment rate, SA | Monthly already |
| `us_claims` | FRED `ICSA`, US initial claims, SA | Week containing the 12th |
| `spread_10y3m` | FRED `T10Y3M`, 10-year minus 3-month Treasury yield | Monthly average of daily values |
| `fedfunds` | FRED `FEDFUNDS`, effective federal funds rate | Monthly already |
| `nj_ur`, `ct_ur`, `pa_ur` | FRED `NJUR`, `CTUR`, `PAUR`, neighboring states' unemployment rates, SA | Monthly already |
| `sp500` | Yahoo Finance `^GSPC`, S&P 500 close | Monthly average of daily values |
| `empire_general` | FRED `GACDISA066MSFRBNY`, NY Fed Empire State Manufacturing Survey, current general business conditions, SA. From 2001-07. | Monthly already |

`empire_general` is a diffusion index: the percent of NY manufacturers reporting better conditions minus the percent reporting worse. Above 0 means conditions are improving; below 0 means they're getting worse.

### Weekly claims: why the 12th, and why NY claims are different

**Why the week containing the 12th.** The unemployment rate comes from the Current Population Survey, which asks people about their work status during the week (Sunday to Saturday) that contains the 12th of the month. Taking claims for that same week measures layoffs over the period the unemployment rate describes. This is standard practice in labor-market forecasting.

FRED dates each claims week by the Saturday it ends on. The week containing the 12th is always the one whose Saturday falls on the 12th to 18th (Saturday the 12th if the 12th is a Saturday, Saturday the 18th if it is a Sunday), and every month has exactly one such Saturday.

**Why NY claims also get a monthly average.** `NYICLAIMS` is not seasonally adjusted, and NY has short spikes of about two weeks in early January and early July (likely end-of-holiday jobs and school-year layoffs). Whether the reference week lands inside a spike depends on the calendar, not the economy. For example:

| | July 2019 | July 2026 |
|---|---|---|
| Reference week | Jul 13: 25,416 (inside spike) | Jul 18: 14,735 (spike just ended) |
| Average of all July weeks | 18,550 | 19,680 |

The reference week suggests July claims fell 42%. The weekly data shows both Julys had a similar spike. Seasonal adjustment then makes this worse: STL learns that July is usually about 1.8x normal and divides every July by that, so July 2026 comes out at roughly half its true level. The monthly average always includes the spike weeks, so it adjusts cleanly. That's why the panel has no seasonally adjusted reference-week NY column: `ny_claims` is kept for reference, but model with `ny_claims_avg_sa`.

`us_claims` doesn't have this problem because `ICSA` is already seasonally adjusted week by week by the Department of Labor.

### Known issues for modelers

- **October 2025 is missing for all unemployment rates** (`ny_ur`, `us_ur`, `nj_ur`, `ct_ur`, `pa_ur`). The federal government shutdown stopped BLS from collecting the household survey that month, so the value was never published. Models that need an unbroken series (ARIMA, ETS) have to handle this gap themselves, for example by interpolating inside the model code.
- **STL seasonal adjustment looks ahead.** STL estimates each month's seasonal pattern partly from later years, so `ny_claims_avg_sa` contains a small amount of future information. For a strict backtest, re-run the adjustment on each training window.
