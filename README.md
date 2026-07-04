# Backtester

A local stock backtesting website: chart any stock, compare moving averages,
view risk/return metrics, backtest trading strategies against buy-and-hold,
and optimize a multi-stock portfolio.

Everything runs locally on your machine. Nothing is deployed to the internet
by default — you open it in your own browser at `http://localhost:8000`.

## Important: read this before you start

This project can't run inside the sandboxed environment it was built in
(that environment blocks access to Yahoo Finance), so **the first real data
pull has to happen on your machine.** That's a one-time step below.

Also worth knowing upfront:
- **Data source is Yahoo Finance via the unofficial `yfinance` library.**
  There's no official Yahoo API, so this can occasionally break if Yahoo
  changes something, and aggressive use can get your IP rate-limited. The
  pipeline paces its requests deliberately slowly to avoid that.
- **Data depth varies by ticker.** Some large caps have decades of history;
  many others only go back as far as their IPO or as far as Yahoo has
  digitized. The UI will tell you a stock's available start date rather than
  silently truncating.
- **Free data only, delayed ~15-20 minutes** during market hours (irrelevant
  for backtesting, matters if you were hoping for live quotes — this isn't
  built for that).
- **Default ticker universe is the S&P 500 (~500 tickers) plus ~110 other
  liquid names** (~600-ish total), not the full ~4,500 US-listed universe we
  discussed. This was a deliberate scope choice to start — see "Expanding
  the ticker universe" below for how to grow it.

## Setup

### 1. Install dependencies

Requires Python 3.10+.

```bash
pip install -r requirements.txt
```

### 2. Run the data pipeline (one-time)

This pulls historical daily prices, dividends, and splits from Yahoo
Finance into a local SQLite database at `backend/data/market.db`.

```bash
cd data_pipeline
python fetch_data.py --backfill
```

This will take a while — the pacing between requests is intentionally
conservative to avoid getting rate-limited (roughly 1.5-2 seconds per
ticker, so ~600 tickers is somewhere around 20-30 minutes). It's safe to
stop and resume: already-fetched tickers are skipped on the next run.

**To test quickly first** with just a handful of tickers:
```bash
python fetch_data.py --backfill --limit 20
```

If a run gets interrupted or a lot of tickers fail, that usually means
Yahoo is throttling your IP — wait an hour or so and re-run the same
command; it'll pick up where it left off.

To refresh with the latest trading day later on (run this periodically,
e.g. once a day):
```bash
python fetch_data.py --update
```

### 3. Start the site

From the project root:
```bash
python run.py
```

This starts the server and opens `http://localhost:8000` in your browser.
(Or manually: `cd backend && uvicorn app:app --reload`, then open the URL
yourself.)

## What's inside

Everything lives on a single scrolling page (a slim sticky nav at the top jumps
to each section):

- **Chart** — search any ticker/company name, chart it, and toggle moving
  averages on/off directly on the same chart via the module underneath it.
  Add a second (or third, etc.) stock and flip on "Compare all added stocks
  instead" to see them as % change side-by-side (moving averages only apply
  to a single focus stock, so that control hides while comparing).
- **Metrics** — Sharpe, Sortino, alpha, beta, max drawdown, Calmar, VaR, and
  more for each stock you've added, each with a hover (i) explaining what it
  means in plain English.
- **Backtest** — run a strategy (moving average crossover, RSI, MACD,
  Bollinger Band reversion) against a stock, compared side-by-side with
  buy-and-hold. Every strategy and every input (fast/slow/signal windows,
  RSI thresholds, transaction cost, dividend reinvestment) has a hover (i)
  explaining it in plain language. Results render below the form.
- **Portfolio Optimizer** — pick a basket of 2+ stocks, see the efficient
  frontier, and get suggested weights for the minimum-risk and
  best-risk-adjusted-return (max Sharpe) portfolios.

## Expanding the ticker universe

`data_pipeline/tickers.py` builds the universe from the live S&P 500 list
(fetched from Wikipedia at pipeline runtime) plus a short hardcoded list of
extra liquid names. To backtest a stock that isn't in either:

1. Add its ticker/name to the `FALLBACK_TICKERS` dict in `tickers.py`, or
2. Just run `fetch_data.py` for it directly — the fetch/store logic works
   for any valid ticker, the universe list just controls what the default
   backfill covers.

Scaling toward the full ~4,500 US-listed universe is very doable, but budget
for it: at the pacing used here, that's many hours of pipeline runtime
(spread across multiple sessions is fine), and a meaningful share of small,
illiquid, or very recently listed tickers may return spotty history or fail
outright from Yahoo. Worth doing incrementally rather than all at once.

## Troubleshooting: a stock's history looks shorter than expected

If a well-established stock (like AAPL or MSFT) only shows data starting at
some recent date instead of its full history, run this to isolate where the
problem is:

```bash
python -c "import yfinance as yf; df = yf.Ticker('AAPL').history(period='max', auto_adjust=False); print('rows:', len(df)); print('range:', df.index.min(), '->', df.index.max())"
```

- **If this also shows a short range** — the issue is upstream of this
  project entirely (Yahoo/yfinance itself), and re-running the pipeline
  won't fix it on its own. Try `pip install --upgrade yfinance` and re-run.
- **If this shows full decades of history** — the issue is specific to
  the pipeline run, most likely because that ticker got written to the
  database with a partial fetch (e.g. an early attempt that failed after
  retries) and later got skipped as "already backfilled." Fix: delete
  `backend/data/market.db` and re-run `python fetch_data.py --backfill`
  from scratch. Since this is a full rebuild, it'll take the full ~20-30
  minutes again, but guarantees no partial/stale entries.

## Known limitations / things not yet built

- No forward-looking projections (Monte Carlo, etc.) — intentionally
  deferred, per your call to keep this backtesting-only for now.
- No transaction-cost realism beyond a flat bps-per-trade assumption (no
  bid-ask spread modeling, no slippage curve).
- No short-selling or leverage in the portfolio optimizer (long-only,
  intentionally, to keep results easy to interpret).
- No survivorship-bias correction — the ticker universe only includes
  currently-listed companies, so long-run backtests will look somewhat
  better than reality (delisted/failed companies aren't in the data).
- Single-user, no accounts/auth — fine for personal local use as-is; would
  need to be added before deploying this somewhere publicly accessible.

## Project structure

```
stockbacktester/
├── requirements.txt
├── run.py                    # convenience launcher
├── data_pipeline/
│   ├── fetch_data.py         # run this first (--backfill, then --update)
│   └── tickers.py            # ticker universe definition
├── backend/
│   ├── app.py                # FastAPI app + all API endpoints
│   ├── database.py           # SQLite access layer
│   ├── metrics.py            # Sharpe/alpha/beta/etc. + tooltip text
│   ├── backtest.py           # strategy signals + backtest engine
│   ├── optimizer.py          # mean-variance portfolio optimization
│   └── data/market.db        # created by the pipeline (not included)
└── frontend/
    ├── index.html
    ├── style.css
    └── app.js                # vanilla JS, no build step needed
```
