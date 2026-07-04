"""
Financial metrics, each paired with a plain-English description meant for
someone without a finance background -- these descriptions are sent to the
frontend and shown in the (i) hover tooltips next to each metric.
"""

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252

METRIC_INFO = {
    "total_return": {
        "label": "Total Return",
        "description": "How much your money grew (or shrank) over the whole period, in percent. A total return of 50% means $1,000 became $1,500.",
    },
    "cagr": {
        "label": "Annualized Return (CAGR)",
        "description": "The steady year-over-year growth rate that would get you from the starting value to the ending value. Lets you compare periods of different lengths on equal footing.",
    },
    "volatility": {
        "label": "Volatility",
        "description": "How much the price bounces around, measured as a yearly percentage. Higher volatility means bigger swings, up and down, both directions.",
    },
    "sharpe": {
        "label": "Sharpe Ratio",
        "description": "Return earned per unit of risk taken, versus a risk-free investment like a T-bill. Above 1 is considered good, above 2 is very good. A negative Sharpe means it underperformed the risk-free rate.",
    },
    "sortino": {
        "label": "Sortino Ratio",
        "description": "Like the Sharpe Ratio, but only counts downside swings as 'risk' -- it doesn't penalize an investment for going up a lot. Higher is better.",
    },
    "max_drawdown": {
        "label": "Max Drawdown",
        "description": "The single largest drop from a peak to a subsequent low over the period. If a stock went from $100 to $60 before recovering, that's a 40% max drawdown -- a way to gauge the worst pain you'd have felt holding it.",
    },
    "calmar": {
        "label": "Calmar Ratio",
        "description": "Annualized return divided by the max drawdown. Answers: 'how much return am I getting relative to the worst crash I had to sit through?' Higher is better.",
    },
    "beta": {
        "label": "Beta",
        "description": "How sensitive the stock is to overall market moves (vs. a benchmark like the S&P 500). Beta of 1 means it moves with the market. Above 1 means bigger swings than the market; below 1 means smaller swings.",
    },
    "alpha": {
        "label": "Alpha",
        "description": "Return the stock generated beyond what its Beta (market sensitivity) would predict, annualized. Positive alpha means it beat what you'd expect given its market risk; negative means it fell short.",
    },
    "var_95": {
        "label": "Value at Risk (95%)",
        "description": "On a typical bad day (the worst 5% of days), roughly how much you could expect to lose in a single day, in percent. A -3% VaR means about 1 day in 20 sees a loss of 3% or worse.",
    },
    "win_rate": {
        "label": "Win Rate",
        "description": "Of all the individual trades a strategy made, the percentage that were profitable. High win rate doesn't guarantee a good strategy -- a few big losses can still outweigh many small wins.",
    },
    "avg_win_loss_ratio": {
        "label": "Avg Win/Loss Ratio",
        "description": "The average size of winning trades divided by the average size of losing trades. Above 1 means winners tend to be bigger than losers, even if there are fewer of them.",
    },
    "correlation": {
        "label": "Correlation vs Benchmark",
        "description": "How closely this stock's day-to-day moves track the benchmark (SPY), from -1 to +1. +1 means they move in lockstep, 0 means no relationship, -1 means they move in opposite directions. This is NOT correlation with your other selected stocks -- for that, see the correlation matrix in the Portfolio Optimizer module below.",
    },
}

RISK_FREE_RATE_ANNUAL = 0.045  # approximate T-bill yield used as the risk-free baseline for Sharpe/Sortino/alpha


def daily_returns(prices: pd.Series) -> pd.Series:
    return prices.pct_change().dropna()


def cagr(prices: pd.Series) -> float:
    if len(prices) < 2:
        return float("nan")
    n_years = (prices.index[-1] - prices.index[0]).days / 365.25
    if n_years <= 0:
        return float("nan")
    return (prices.iloc[-1] / prices.iloc[0]) ** (1 / n_years) - 1


def total_return(prices: pd.Series) -> float:
    if len(prices) < 2:
        return float("nan")
    return prices.iloc[-1] / prices.iloc[0] - 1


def annualized_volatility(returns: pd.Series) -> float:
    return returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)


def sharpe_ratio(returns: pd.Series, risk_free_annual: float = RISK_FREE_RATE_ANNUAL) -> float:
    if returns.std() < 1e-9 or len(returns) == 0:
        return float("nan")
    rf_daily = risk_free_annual / TRADING_DAYS_PER_YEAR
    excess = returns - rf_daily
    return (excess.mean() / returns.std()) * np.sqrt(TRADING_DAYS_PER_YEAR)


def sortino_ratio(returns: pd.Series, risk_free_annual: float = RISK_FREE_RATE_ANNUAL) -> float:
    rf_daily = risk_free_annual / TRADING_DAYS_PER_YEAR
    excess = returns - rf_daily
    downside = excess[excess < 0]
    downside_std = downside.std()
    # Use an epsilon rather than exact ==0: a strategy that never trades produces a
    # theoretically-constant return series, but floating point arithmetic leaves a tiny
    # non-zero residue (e.g. 1e-20) that would otherwise slip past an exact equality
    # check and blow up into a nonsensical ratio like -1e17.
    if downside_std < 1e-9 or np.isnan(downside_std) or len(returns) == 0:
        return float("nan")
    return (excess.mean() / downside_std) * np.sqrt(TRADING_DAYS_PER_YEAR)


def max_drawdown(prices: pd.Series) -> float:
    if len(prices) < 2:
        return float("nan")
    running_max = prices.cummax()
    drawdown = prices / running_max - 1
    return drawdown.min()


def calmar_ratio(prices: pd.Series) -> float:
    mdd = max_drawdown(prices)
    if abs(mdd) < 1e-9 or np.isnan(mdd):
        return float("nan")
    return cagr(prices) / abs(mdd)


def beta_alpha(returns: pd.Series, benchmark_returns: pd.Series, risk_free_annual: float = RISK_FREE_RATE_ANNUAL) -> tuple[float, float]:
    """Returns (beta, annualized alpha) via simple linear regression against benchmark returns."""
    aligned = pd.concat([returns, benchmark_returns], axis=1, join="inner").dropna()
    if len(aligned) < 20:
        return float("nan"), float("nan")
    r, b = aligned.iloc[:, 0], aligned.iloc[:, 1]
    cov = np.cov(r, b)
    beta = cov[0, 1] / cov[1, 1] if cov[1, 1] != 0 else float("nan")
    rf_daily = risk_free_annual / TRADING_DAYS_PER_YEAR
    daily_alpha = (r.mean() - rf_daily) - beta * (b.mean() - rf_daily)
    annualized_alpha = daily_alpha * TRADING_DAYS_PER_YEAR
    return beta, annualized_alpha


def value_at_risk_95(returns: pd.Series) -> float:
    if len(returns) == 0:
        return float("nan")
    return np.percentile(returns, 5)


def correlation(returns_a: pd.Series, returns_b: pd.Series) -> float:
    aligned = pd.concat([returns_a, returns_b], axis=1, join="inner").dropna()
    if len(aligned) < 5:
        return float("nan")
    return aligned.iloc[:, 0].corr(aligned.iloc[:, 1])


def compute_all_metrics(prices: pd.Series, benchmark_prices: pd.Series | None = None) -> dict:
    """Compute the full metrics panel for a single price series."""
    rets = daily_returns(prices)
    result = {
        "total_return": total_return(prices),
        "cagr": cagr(prices),
        "volatility": annualized_volatility(rets),
        "sharpe": sharpe_ratio(rets),
        "sortino": sortino_ratio(rets),
        "max_drawdown": max_drawdown(prices),
        "calmar": calmar_ratio(prices),
        "var_95": value_at_risk_95(rets),
    }
    if benchmark_prices is not None and len(benchmark_prices) > 0:
        bench_rets = daily_returns(benchmark_prices)
        beta, alpha = beta_alpha(rets, bench_rets)
        result["beta"] = beta
        result["alpha"] = alpha
        result["correlation"] = correlation(rets, bench_rets)
    return result
