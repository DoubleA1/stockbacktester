"""Thin SQLite access layer. Kept deliberately simple (raw SQL, no ORM) since
the schema is small and stable. All reads/writes go through here so the rest
of the backend doesn't need to know about SQL."""

import os
import sqlite3
from pathlib import Path

import pandas as pd

# By default the database lives next to this file (data/market.db) for local use.
# In hosted environments (e.g. a Render persistent disk) set the MARKET_DB_PATH
# environment variable to an absolute path so the data survives redeploys.
_DEFAULT_DB_PATH = Path(__file__).parent / "data" / "market.db"
DB_PATH = Path(os.environ["MARKET_DB_PATH"]) if os.environ.get("MARKET_DB_PATH") else _DEFAULT_DB_PATH


def get_connection() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"No database found at {DB_PATH}. Run the data pipeline first:\n"
            f"  cd data_pipeline && python fetch_data.py --backfill"
        )
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    return conn


def db_exists() -> bool:
    return DB_PATH.exists()


def list_tickers(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT ticker, name, first_date, last_date FROM tickers ORDER BY ticker", conn
    )


def search_tickers(conn: sqlite3.Connection, query: str, limit: int = 15) -> pd.DataFrame:
    q = f"%{query.upper()}%"
    qname = f"%{query}%"
    return pd.read_sql_query(
        """SELECT ticker, name, first_date, last_date FROM tickers
           WHERE UPPER(ticker) LIKE ? OR name LIKE ?
           ORDER BY
             CASE WHEN UPPER(ticker) = UPPER(?) THEN 0
                  WHEN UPPER(ticker) LIKE ? THEN 1
                  ELSE 2 END,
             ticker
           LIMIT ?""",
        conn,
        params=(q, qname, query, f"{query.upper()}%", limit),
    )


def get_prices(conn: sqlite3.Connection, ticker: str, start_date: str | None = None) -> pd.DataFrame:
    if start_date:
        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, adj_close, volume FROM prices WHERE ticker = ? AND date >= ? ORDER BY date",
            conn, params=(ticker, start_date),
        )
    else:
        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, adj_close, volume FROM prices WHERE ticker = ? ORDER BY date",
            conn, params=(ticker,),
        )
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
    return df


def get_dividends(conn: sqlite3.Connection, ticker: str) -> pd.DataFrame:
    df = pd.read_sql_query("SELECT date, amount FROM dividends WHERE ticker = ? ORDER BY date", conn, params=(ticker,))
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
    return df
