"""
FastAPI backend for the stock backtester.

This is the ONLY thing that talks to the database -- it never calls Yahoo
Finance directly. Run the data pipeline first (see data_pipeline/fetch_data.py),
then start this with:

    uvicorn app:app --reload

and open http://localhost:8000 in your browser.
"""

from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

import database as db
from metrics import compute_all_metrics, METRIC_INFO, daily_returns
from backtest import run_backtest, STRATEGIES
from optimizer import optimize_portfolio

app = FastAPI(title="Stock Backtester API")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

DEFAULT_BENCHMARK = "SPY"


def sanitize_floats(d: dict) -> dict:
    """Replace NaN/Inf with None so FastAPI's JSON encoder never chokes on them
    (Python floats allow NaN/Inf; strict JSON does not)."""
    clean = {}
    for k, v in d.items():
        if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
            clean[k] = None
        else:
            clean[k] = v
    return clean


def resolve_range_start(range_key: str, last_available_date: Optional[pd.Timestamp] = None) -> Optional[str]:
    """Map a UI range key ('5D','1M','3M','1Y','YTD','5Y','ALL') to a start date string."""
    today = last_available_date if last_available_date is not None else pd.Timestamp.today()
    range_key = (range_key or "1Y").upper()
    if range_key == "5D":
        start = today - timedelta(days=8)
    elif range_key == "1M":
        start = today - timedelta(days=32)
    elif range_key == "3M":
        start = today - timedelta(days=93)
    elif range_key == "YTD":
        start = pd.Timestamp(year=today.year, month=1, day=1)
    elif range_key == "1Y":
        start = today - timedelta(days=366)
    elif range_key == "5Y":
        start = today - timedelta(days=366 * 5)
    elif range_key == "ALL":
        return None
    else:
        start = today - timedelta(days=366)
    return start.strftime("%Y-%m-%d")


def load_prices_for_range(conn, ticker: str, range_key: str) -> pd.DataFrame:
    full = db.get_prices(conn, ticker)
    if full.empty:
        return full
    start_date = resolve_range_start(range_key, last_available_date=full.index.max())
    if start_date:
        return full[full.index >= start_date]
    return full


@app.get("/api/health")
def health():
    return {"status": "ok", "database_ready": db.db_exists()}


@app.get("/api/tickers")
def get_tickers():
    conn = db.get_connection()
    df = db.list_tickers(conn)
    conn.close()
    return df.to_dict(orient="records")


@app.get("/api/search")
def search(q: str = Query(..., min_length=1)):
    conn = db.get_connection()
    df = db.search_tickers(conn, q)
    conn.close()
    return df.to_dict(orient="records")


@app.get("/api/metric-info")
def metric_info():
    return METRIC_INFO


@app.get("/api/strategies")
def strategies():
    return {
        key: {
            "label": v["label"],
            "description": v["description"],
            "default_params": v["params"],
            "param_info": v.get("param_info", {}),
        }
        for key, v in STRATEGIES.items()
    }


@app.get("/api/prices")
def get_prices(tickers: str = Query(...), range: str = Query("1Y")):
    """Prices for one or more tickers (comma-separated), for charting."""
    conn = db.get_connection()
    result = {}
    for ticker in [t.strip().upper() for t in tickers.split(",") if t.strip()]:
        df = load_prices_for_range(conn, ticker, range)
        if df.empty:
            result[ticker] = {"error": "No data found for this ticker. Has the pipeline fetched it?"}
            continue
        result[ticker] = {
            "dates": [str(d.date()) for d in df.index],
            "close": [round(float(v), 2) for v in df["close"]],
            "adj_close": [round(float(v), 2) for v in df["adj_close"]],
            "volume": [int(v) for v in df["volume"]],
            "first_available_date": str(df.index.min().date()),
        }
    conn.close()
    return result


@app.get("/api/moving-averages")
def moving_averages(ticker: str, windows: str = Query("20,50,200"), range: str = Query("1Y")):
    conn = db.get_connection()
    ticker = ticker.upper()
    full = db.get_prices(conn, ticker)
    conn.close()
    if full.empty:
        raise HTTPException(404, f"No data for {ticker}")

    window_list = [int(w.strip()) for w in windows.split(",") if w.strip()]
    # Line/MA basis is adjusted close -- avoids showing a misleading price "cliff" on split dates.
    # (Candlestick OHLC below is intentionally raw/unadjusted, matching how it actually traded that day.)
    ma_series = {w: full["adj_close"].rolling(w).mean() for w in window_list}

    start_date = resolve_range_start(range, last_available_date=full.index.max())
    view = full if start_date is None else full[full.index >= start_date]

    return {
        "ticker": ticker,
        "dates": [str(d.date()) for d in view.index],
        "close": [round(float(v), 2) for v in view["adj_close"]],
        "open": [round(float(v), 2) for v in view["open"]],
        "high": [round(float(v), 2) for v in view["high"]],
        "low": [round(float(v), 2) for v in view["low"]],
        "raw_close": [round(float(v), 2) for v in view["close"]],
        "moving_averages": {
            str(w): [None if pd.isna(v) else round(float(v), 2) for v in ma_series[w].reindex(view.index)]
            for w in window_list
        },
    }


@app.get("/api/metrics")
def get_metrics(tickers: str = Query(...), range: str = Query("1Y"), benchmark: str = Query(DEFAULT_BENCHMARK)):
    conn = db.get_connection()
    benchmark = benchmark.upper()
    bench_df = load_prices_for_range(conn, benchmark, range)
    bench_prices = bench_df["adj_close"] if not bench_df.empty else None

    result = {}
    for ticker in [t.strip().upper() for t in tickers.split(",") if t.strip()]:
        df = load_prices_for_range(conn, ticker, range)
        if df.empty or len(df) < 5:
            result[ticker] = {"error": "Not enough data for this ticker in the selected range."}
            continue
        m = compute_all_metrics(df["adj_close"], bench_prices if ticker != benchmark else None)
        m_rounded = {k: (round(float(v), 4) if v is not None else None) for k, v in m.items()}
        result[ticker] = sanitize_floats(m_rounded)
        result[ticker]["data_points"] = len(df)
        result[ticker]["available_since"] = str(df.index.min().date())
    conn.close()
    return {"benchmark": benchmark, "metrics": result}


@app.post("/api/backtest")
def backtest(payload: dict = Body(...)):
    """
    Body: {
      "ticker": "AAPL",
      "strategy": "sma_crossover",
      "params": {"fast": 50, "slow": 200},
      "range": "5Y",
      "dividend_reinvest": true,
      "transaction_cost_bps": 5,
      "initial_capital": 10000
    }
    """
    ticker = payload.get("ticker", "").upper()
    strategy = payload.get("strategy")
    if not ticker or strategy not in STRATEGIES:
        raise HTTPException(400, f"Provide a valid ticker and one of strategies: {list(STRATEGIES.keys())}")

    conn = db.get_connection()
    df = load_prices_for_range(conn, ticker, payload.get("range", "5Y"))
    if df.empty or len(df) < 30:
        conn.close()
        raise HTTPException(400, "Not enough price history for this ticker/range to run a backtest.")
    df = df.rename(columns={"adj_close": "close_adj"})
    df["close"] = df["adj_close"] if "adj_close" in df.columns else df["close_adj"]

    divs = db.get_dividends(conn, ticker)
    div_series = divs["amount"] if not divs.empty else pd.Series(dtype=float)
    conn.close()

    try:
        result = run_backtest(
            df=df,
            dividends=div_series,
            strategy_key=strategy,
            params=payload.get("params", {}),
            dividend_reinvest=payload.get("dividend_reinvest", True),
            transaction_cost_bps=payload.get("transaction_cost_bps", 5.0),
            initial_capital=payload.get("initial_capital", 10000.0),
        )
    except Exception as e:
        raise HTTPException(400, f"Backtest failed: {e}")

    result["strategy_metrics"] = sanitize_floats(result["strategy_metrics"])
    result["buy_hold_metrics"] = sanitize_floats(result["buy_hold_metrics"])
    result["ticker"] = ticker
    result["strategy"] = strategy
    return result


@app.post("/api/optimize")
def optimize(payload: dict = Body(...)):
    """
    Body: {"tickers": ["AAPL","MSFT","NVDA"], "range": "5Y"}
    """
    tickers = [t.strip().upper() for t in payload.get("tickers", []) if t.strip()]
    if len(tickers) < 2:
        raise HTTPException(400, "Provide at least 2 tickers to optimize a portfolio.")

    conn = db.get_connection()
    price_frames = {}
    for ticker in tickers:
        df = load_prices_for_range(conn, ticker, payload.get("range", "5Y"))
        if df.empty:
            conn.close()
            raise HTTPException(400, f"No data for {ticker}. Has the pipeline fetched it?")
        price_frames[ticker] = df["adj_close"]
    conn.close()

    prices_df = pd.DataFrame(price_frames).dropna()
    if len(prices_df) < 30:
        raise HTTPException(400, "Not enough overlapping history across these tickers for the selected range.")

    returns_df = prices_df.pct_change().dropna()
    result = optimize_portfolio(returns_df)
    return result


# --- Serve the frontend ---
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def index():
        return FileResponse(str(FRONTEND_DIR / "index.html"))
