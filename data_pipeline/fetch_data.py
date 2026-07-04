"""
Data pipeline: pulls historical daily price data (+ dividends & splits) from
Yahoo Finance via yfinance, and stores it in a local SQLite database.

WHY THIS IS A SEPARATE SCRIPT FROM THE WEBSITE:
Yahoo Finance has no official API and will rate-limit or temporarily block
an IP that hits it too fast or too often. So this script runs ONCE (full
backfill) and then can be re-run periodically (e.g. daily via cron) to pick
up just the newest bars. The website itself (backend/app.py) only ever
reads from the local database it builds -- it never calls Yahoo directly.

USAGE:
    python fetch_data.py --backfill      # first run: pull full history for every ticker
    python fetch_data.py --update        # subsequent runs: pull only new days since last fetch
    python fetch_data.py --backfill --limit 20   # test with just the first 20 tickers

Both modes are safe to interrupt and re-run -- already-fetched tickers are
skipped (or only updated incrementally), so you can resume a big backfill
run across multiple sessions if Yahoo starts throttling you.
"""

import argparse
import logging
import os
import random
import sqlite3
import sys
import time
from datetime import datetime, date
from pathlib import Path

try:
    import yfinance as yf
    import pandas as pd
except ImportError:
    print("Missing dependencies. Run: pip install -r requirements.txt")
    sys.exit(1)

from tickers import get_ticker_universe

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("pipeline.log")],
)
logger = logging.getLogger(__name__)

# Writes to the same database the website reads. Honors MARKET_DB_PATH (used in
# hosted setups so the pipeline updates the DB on the persistent disk) and falls
# back to the local backend/data/market.db for local use.
_DEFAULT_DB_PATH = Path(__file__).parent.parent / "backend" / "data" / "market.db"
DB_PATH = Path(os.environ["MARKET_DB_PATH"]) if os.environ.get("MARKET_DB_PATH") else _DEFAULT_DB_PATH

# Pacing: yfinance is a scraper hitting Yahoo's unofficial endpoints. Community
# reports suggest a few hundred requests/day per IP before throttling. These
# delays are conservative on purpose -- a slow, complete backfill beats a fast
# one that gets your IP temporarily blocked partway through.
MIN_DELAY = 1.0
MAX_DELAY = 2.5
MAX_RETRIES = 3


def init_db(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tickers (
            ticker TEXT PRIMARY KEY,
            name TEXT,
            first_date TEXT,
            last_date TEXT,
            last_updated TEXT
        );
        CREATE TABLE IF NOT EXISTS prices (
            ticker TEXT,
            date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            adj_close REAL,
            volume INTEGER,
            PRIMARY KEY (ticker, date)
        );
        CREATE TABLE IF NOT EXISTS dividends (
            ticker TEXT,
            date TEXT,
            amount REAL,
            PRIMARY KEY (ticker, date)
        );
        CREATE TABLE IF NOT EXISTS splits (
            ticker TEXT,
            date TEXT,
            ratio REAL,
            PRIMARY KEY (ticker, date)
        );
        CREATE INDEX IF NOT EXISTS idx_prices_ticker_date ON prices(ticker, date);
    """)
    conn.commit()


def fetch_one(ticker: str, start: str | None = None) -> pd.DataFrame | None:
    """Fetch full or incremental history for a single ticker, with retries."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            t = yf.Ticker(ticker)
            if start:
                df = t.history(start=start, auto_adjust=False, actions=True)
            else:
                df = t.history(period="max", auto_adjust=False, actions=True)
            if df is None or df.empty:
                return None
            return df
        except Exception as e:
            wait = attempt * 5
            logger.warning(f"{ticker}: attempt {attempt} failed ({e}). Retrying in {wait}s...")
            time.sleep(wait)
    logger.error(f"{ticker}: giving up after {MAX_RETRIES} attempts.")
    return None


def store(conn: sqlite3.Connection, ticker: str, name: str, df: pd.DataFrame):
    df = df.reset_index()
    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")

    price_rows = [
        (ticker, r["Date"], r["Open"], r["High"], r["Low"], r["Close"], r["Adj Close"], int(r["Volume"]) if pd.notna(r["Volume"]) else 0)
        for _, r in df.iterrows()
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, adj_close, volume) VALUES (?,?,?,?,?,?,?,?)",
        price_rows,
    )

    if "Dividends" in df.columns:
        div_rows = [(ticker, r["Date"], r["Dividends"]) for _, r in df.iterrows() if r["Dividends"] and r["Dividends"] > 0]
        if div_rows:
            conn.executemany("INSERT OR REPLACE INTO dividends (ticker, date, amount) VALUES (?,?,?)", div_rows)

    if "Stock Splits" in df.columns:
        split_rows = [(ticker, r["Date"], r["Stock Splits"]) for _, r in df.iterrows() if r["Stock Splits"] and r["Stock Splits"] > 0]
        if split_rows:
            conn.executemany("INSERT OR REPLACE INTO splits (ticker, date, ratio) VALUES (?,?,?)", split_rows)

    first_date, last_date = df["Date"].min(), df["Date"].max()
    conn.execute(
        """INSERT INTO tickers (ticker, name, first_date, last_date, last_updated)
           VALUES (?,?,?,?,?)
           ON CONFLICT(ticker) DO UPDATE SET
             name=excluded.name,
             first_date=MIN(tickers.first_date, excluded.first_date),
             last_date=excluded.last_date,
             last_updated=excluded.last_updated""",
        (ticker, name, first_date, last_date, datetime.now().isoformat()),
    )
    conn.commit()


def run(mode: str, limit: int | None):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    universe = get_ticker_universe()
    tickers = list(universe.items())
    if limit:
        tickers = tickers[:limit]

    existing = {row[0]: row[1] for row in conn.execute("SELECT ticker, last_date FROM tickers")}

    total = len(tickers)
    fetched, skipped, failed = 0, 0, 0

    for i, (ticker, name) in enumerate(tickers, start=1):
        start_date = None
        if mode == "update" and ticker in existing:
            start_date = existing[ticker]  # re-pull from last known date (covers any late corrections)
        elif mode == "backfill" and ticker in existing:
            logger.info(f"[{i}/{total}] {ticker}: already backfilled, skipping (use --update to refresh). ")
            skipped += 1
            continue

        logger.info(f"[{i}/{total}] Fetching {ticker} ({name})...")
        df = fetch_one(ticker, start=start_date)
        if df is None:
            failed += 1
            continue

        store(conn, ticker, name, df)
        fetched += 1

        time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

    conn.close()
    logger.info(f"Done. Fetched: {fetched}, Skipped: {skipped}, Failed: {failed}, Total: {total}")
    if failed > total * 0.3:
        logger.warning(
            "More than 30% of tickers failed -- this usually means Yahoo is rate-limiting this IP. "
            "Wait a while (an hour or more) and re-run with the same mode; already-fetched tickers "
            "will be skipped automatically."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch historical stock data from Yahoo Finance into a local SQLite database.")
    parser.add_argument("--backfill", action="store_true", help="Full history backfill for tickers not yet in the database.")
    parser.add_argument("--update", action="store_true", help="Incremental update for tickers already in the database.")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N tickers (useful for testing).")
    args = parser.parse_args()

    if not args.backfill and not args.update:
        print("Specify --backfill (first run) or --update (subsequent runs). See --help.")
        sys.exit(1)

    run(mode="backfill" if args.backfill else "update", limit=args.limit)
