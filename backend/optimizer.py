"""
Mean-variance portfolio optimization (Modern Portfolio Theory), long-only.

Given a basket of tickers' historical daily returns, computes:
  - the minimum-variance portfolio (lowest possible risk for that basket)
  - the maximum-Sharpe portfolio ("tangency" portfolio -- best risk-adjusted return)
  - the efficient frontier (best possible return at each risk level)

Long-only (weights >= 0, sum to 1) to keep results intuitive for someone
without a finance background -- no short-selling or leverage.
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from metrics import TRADING_DAYS_PER_YEAR, RISK_FREE_RATE_ANNUAL


def _portfolio_stats(weights: np.ndarray, mean_returns: np.ndarray, cov_matrix: np.ndarray) -> tuple[float, float]:
    port_return = float(np.dot(weights, mean_returns)) * TRADING_DAYS_PER_YEAR
    port_vol = float(np.sqrt(weights.T @ cov_matrix @ weights)) * np.sqrt(TRADING_DAYS_PER_YEAR)
    return port_return, port_vol


def _min_variance(mean_returns, cov_matrix, target_return=None):
    n = len(mean_returns)
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
    if target_return is not None:
        constraints.append({
            "type": "eq",
            "fun": lambda w: np.dot(w, mean_returns) * TRADING_DAYS_PER_YEAR - target_return,
        })
    bounds = tuple((0, 1) for _ in range(n))
    init = np.repeat(1 / n, n)

    def objective(w):
        return w.T @ cov_matrix @ w

    result = minimize(objective, init, method="SLSQP", bounds=bounds, constraints=constraints, options={"maxiter": 500})
    return result


def _max_sharpe(mean_returns, cov_matrix, risk_free_annual=RISK_FREE_RATE_ANNUAL):
    n = len(mean_returns)
    bounds = tuple((0, 1) for _ in range(n))
    init = np.repeat(1 / n, n)
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]

    def neg_sharpe(w):
        ret, vol = _portfolio_stats(w, mean_returns, cov_matrix)
        if vol == 0:
            return 1e6
        return -((ret - risk_free_annual) / vol)

    result = minimize(neg_sharpe, init, method="SLSQP", bounds=bounds, constraints=constraints, options={"maxiter": 500})
    return result


def optimize_portfolio(returns_df: pd.DataFrame, n_frontier_points: int = 25) -> dict:
    """
    returns_df: DataFrame of daily returns, one column per ticker (already aligned/dropna'd).
    """
    tickers = list(returns_df.columns)
    mean_returns = returns_df.mean().values
    cov_matrix = returns_df.cov().values

    # Min variance portfolio
    min_var_result = _min_variance(mean_returns, cov_matrix)
    min_var_weights = min_var_result.x
    min_var_return, min_var_vol = _portfolio_stats(min_var_weights, mean_returns, cov_matrix)

    # Max Sharpe portfolio
    max_sharpe_result = _max_sharpe(mean_returns, cov_matrix)
    max_sharpe_weights = max_sharpe_result.x
    max_sharpe_return, max_sharpe_vol = _portfolio_stats(max_sharpe_weights, mean_returns, cov_matrix)
    max_sharpe_ratio = (max_sharpe_return - RISK_FREE_RATE_ANNUAL) / max_sharpe_vol if max_sharpe_vol > 0 else float("nan")

    # Efficient frontier: sweep target returns between min-var return and the max individual asset return
    max_asset_return = float(np.max(mean_returns) * TRADING_DAYS_PER_YEAR)
    target_returns = np.linspace(min_var_return, max_asset_return * 0.98, n_frontier_points)
    frontier = []
    for target in target_returns:
        res = _min_variance(mean_returns, cov_matrix, target_return=target)
        if res.success:
            ret, vol = _portfolio_stats(res.x, mean_returns, cov_matrix)
            frontier.append({"return": ret, "volatility": vol})

    # Individual assets (for plotting alongside the frontier)
    individual = []
    for i, ticker in enumerate(tickers):
        asset_return = float(mean_returns[i] * TRADING_DAYS_PER_YEAR)
        asset_vol = float(np.sqrt(cov_matrix[i, i]) * np.sqrt(TRADING_DAYS_PER_YEAR))
        individual.append({"ticker": ticker, "return": asset_return, "volatility": asset_vol})

    return {
        "tickers": tickers,
        "min_variance_portfolio": {
            "weights": {t: round(float(w), 4) for t, w in zip(tickers, min_var_weights)},
            "expected_return": min_var_return,
            "volatility": min_var_vol,
        },
        "max_sharpe_portfolio": {
            "weights": {t: round(float(w), 4) for t, w in zip(tickers, max_sharpe_weights)},
            "expected_return": max_sharpe_return,
            "volatility": max_sharpe_vol,
            "sharpe_ratio": max_sharpe_ratio,
        },
        "efficient_frontier": frontier,
        "individual_assets": individual,
        "correlation_matrix": returns_df.corr().round(3).to_dict(),
    }
