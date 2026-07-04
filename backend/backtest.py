"""
Backtest engine.

Design: each strategy is a function that takes a price DataFrame and
parameters, and returns a Series of positions (1 = fully invested / long,
0 = in cash) indexed the same as the prices. The engine then simulates
both that strategy AND a buy-and-hold benchmark over the same period so
they're always compared apples-to-apples.
"""

import numpy as np
import pandas as pd

from metrics import compute_all_metrics


# ---------------------------------------------------------------------------
# Strategy signal generators
# ---------------------------------------------------------------------------

def signal_sma_crossover(df: pd.DataFrame, fast: int = 50, slow: int = 200) -> pd.Series:
    """Classic 'golden cross' style strategy: long when fast MA is above slow MA."""
    fast_ma = df["close"].rolling(fast).mean()
    slow_ma = df["close"].rolling(slow).mean()
    position = (fast_ma > slow_ma).astype(int)
    return position


def signal_rsi(df: pd.DataFrame, period: int = 14, oversold: float = 30, overbought: float = 70) -> pd.Series:
    """Long when RSI drops below 'oversold' (dip-buy), exit when it rises above 'overbought'."""
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    position = pd.Series(0, index=df.index)
    in_position = False
    for i in range(len(df)):
        if pd.isna(rsi.iloc[i]):
            continue
        if not in_position and rsi.iloc[i] < oversold:
            in_position = True
        elif in_position and rsi.iloc[i] > overbought:
            in_position = False
        position.iloc[i] = 1 if in_position else 0
    return position


def signal_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    """Long when MACD line is above its signal line."""
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return (macd_line > signal_line).astype(int)


def signal_bollinger_reversion(df: pd.DataFrame, period: int = 20, num_std: float = 2.0) -> pd.Series:
    """Mean-reversion: buy when price drops below the lower band, sell when it reverts to the middle band."""
    mid = df["close"].rolling(period).mean()
    std = df["close"].rolling(period).std()
    lower = mid - num_std * std

    position = pd.Series(0, index=df.index)
    in_position = False
    for i in range(len(df)):
        if pd.isna(mid.iloc[i]):
            continue
        if not in_position and df["close"].iloc[i] < lower.iloc[i]:
            in_position = True
        elif in_position and df["close"].iloc[i] >= mid.iloc[i]:
            in_position = False
        position.iloc[i] = 1 if in_position else 0
    return position


STRATEGIES = {
    "sma_crossover": {
        "label": "Moving Average Crossover",
        "description": "Tracks two rolling averages of the price, a fast (short-term) one and a slow (long-term) one. Buys when the fast average climbs above the slow average (a sign the stock has recent upward momentum), and sells when it drops back below. Tends to do well in strong trends, poorly in choppy sideways markets.",
        "fn": signal_sma_crossover,
        "params": {"fast": 50, "slow": 200},
        "param_info": {
            "fast": "The shorter averaging window, in trading days. Reacts quickly to recent price moves. 50 days is a common choice.",
            "slow": "The longer averaging window, in trading days. Moves slowly and smooths out day-to-day noise. 200 days is a common choice.",
        },
    },
    "rsi": {
        "label": "RSI Dip Buyer",
        "description": "Measures whether a stock has moved up or down 'too fast' recently using an indicator called RSI (Relative Strength Index, scaled 0-100). Buys when RSI drops below the oversold line (the stock has fallen sharply and may be due for a bounce), and sells once RSI climbs back above the overbought line.",
        "fn": signal_rsi,
        "params": {"period": 14, "oversold": 30, "overbought": 70},
        "param_info": {
            "period": "How many days of price history are used to calculate RSI. 14 days is the standard default.",
            "oversold": "RSI level (0-100) below which the stock is considered 'oversold' and gets bought. Lower = waits for a sharper drop before buying.",
            "overbought": "RSI level (0-100) above which the stock is considered 'overbought' and gets sold.",
        },
    },
    "macd": {
        "label": "MACD Crossover",
        "description": "A momentum-based cousin of the moving average crossover. Compares a fast and slow average to build a 'MACD line', then compares that line to its own smoothed average (the 'signal line'). Buys when MACD crosses above its signal line, sells when it crosses back below. Tends to react a bit faster than a plain moving average crossover.",
        "fn": signal_macd,
        "params": {"fast": 12, "slow": 26, "signal": 9},
        "param_info": {
            "fast": "The shorter averaging window (in days) used to build the MACD line. 12 is the standard default.",
            "slow": "The longer averaging window (in days) used to build the MACD line. 26 is the standard default.",
            "signal": "How many days used to smooth the MACD line into the 'signal line' it's compared against. 9 is the standard default.",
        },
    },
    "bollinger_reversion": {
        "label": "Bollinger Band Reversion",
        "description": "Draws a 'normal range' band around the average price based on how much it typically fluctuates. Buys when the price falls unusually far below that band (a statistical bargain), and sells once it climbs back to the average. A mean-reversion, 'buy the dip' approach.",
        "fn": signal_bollinger_reversion,
        "params": {"period": 20, "num_std": 2.0},
        "param_info": {
            "period": "How many days used to calculate the average price and its typical range. 20 days is a common choice.",
            "num_std": "How many standard deviations below average counts as 'unusually cheap' before buying. 2.0 is a common default — higher means it waits for a bigger drop.",
        },
    },
}


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------

def run_backtest(
    df: pd.DataFrame,
    dividends: pd.Series,
    strategy_key: str,
    params: dict,
    dividend_reinvest: bool = True,
    transaction_cost_bps: float = 5.0,
    initial_capital: float = 10000.0,
) -> dict:
    """
    df: DataFrame with 'close' column, indexed by date, already trimmed to the backtest window.
    dividends: Series of dividend amounts indexed by date (may be empty).
    Returns strategy vs buy-and-hold equity curves + metrics + trade log.
    """
    if strategy_key not in STRATEGIES:
        raise ValueError(f"Unknown strategy '{strategy_key}'")

    strat_def = STRATEGIES[strategy_key]
    merged_params = {**strat_def["params"], **(params or {})}
    position = strat_def["fn"](df, **merged_params)
    position = position.fillna(0).astype(int)

    close = df["close"]
    daily_ret = close.pct_change().fillna(0)

    if dividend_reinvest and dividends is not None and len(dividends) > 0:
        div_yield = (dividends.reindex(close.index).fillna(0) / close.shift(1).replace(0, np.nan)).fillna(0)
        daily_ret = daily_ret + div_yield

    # --- Buy & hold ---
    bh_equity = initial_capital * (1 + daily_ret).cumprod()
    bh_equity.iloc[0] = initial_capital

    # --- Strategy ---
    # position.shift(1): trade executes at the *next* day's close relative to the signal (avoids lookahead bias)
    strat_position = position.shift(1).fillna(0)
    strat_daily_ret = strat_position * daily_ret

    # transaction costs: charge cost_bps whenever position changes (buy or sell)
    trades = strat_position.diff().fillna(0) != 0
    cost = (transaction_cost_bps / 10000.0) * trades.astype(int)
    strat_daily_ret = strat_daily_ret - cost

    strat_equity = initial_capital * (1 + strat_daily_ret).cumprod()
    strat_equity.iloc[0] = initial_capital

    # --- Trade log & win rate ---
    trade_dates = strat_position.diff().fillna(0)
    entries = df.index[trade_dates == 1]
    exits = df.index[trade_dates == -1]
    trade_log = []
    entry_price = None
    entry_date = None
    for d in df.index:
        if trade_dates.loc[d] == 1:
            entry_date, entry_price = d, close.loc[d]
        elif trade_dates.loc[d] == -1 and entry_price is not None:
            exit_price = close.loc[d]
            pnl_pct = exit_price / entry_price - 1
            trade_log.append({
                "entry_date": str(entry_date.date()), "exit_date": str(d.date()),
                "entry_price": round(float(entry_price), 2), "exit_price": round(float(exit_price), 2),
                "return_pct": round(float(pnl_pct) * 100, 2),
            })
            entry_price = None

    wins = [t for t in trade_log if t["return_pct"] > 0]
    losses = [t for t in trade_log if t["return_pct"] <= 0]
    win_rate = len(wins) / len(trade_log) if trade_log else float("nan")
    avg_win = np.mean([t["return_pct"] for t in wins]) if wins else 0
    avg_loss = np.mean([abs(t["return_pct"]) for t in losses]) if losses else 0
    avg_win_loss_ratio = (avg_win / avg_loss) if avg_loss > 0 else float("nan")

    strat_metrics = compute_all_metrics(strat_equity)
    strat_metrics["win_rate"] = win_rate
    strat_metrics["avg_win_loss_ratio"] = avg_win_loss_ratio
    bh_metrics = compute_all_metrics(bh_equity)

    return {
        "dates": [str(d.date()) for d in df.index],
        "strategy_equity": [round(float(v), 2) for v in strat_equity],
        "buy_hold_equity": [round(float(v), 2) for v in bh_equity],
        "strategy_metrics": strat_metrics,
        "buy_hold_metrics": bh_metrics,
        "trade_log": trade_log,
        "num_trades": len(trade_log),
    }
