"""
Ticker universe for the backtester.

Strategy: try to pull the *current* S&P 500 constituent list live from
Wikipedia (this runs on your machine with normal internet access, so it
works fine even though it can't run inside the build sandbox). If that
fails for any reason (no internet, page structure changed), we fall back
to a hardcoded snapshot so the pipeline never just dies.

We also throw in a short list of other highly liquid, well-known names
that aren't always in the S&P 500 (e.g. recent IPOs) since you'll likely
want to chart/backtest those too.
"""

import logging

logger = logging.getLogger(__name__)

# Fallback snapshot (large, liquid, well-known names) in case the live
# Wikipedia fetch fails. Not exhaustive -- just enough that the pipeline
# always has something real to work with.
FALLBACK_TICKERS = {
    "AAPL": "Apple Inc.", "MSFT": "Microsoft Corporation", "GOOGL": "Alphabet Inc.",
    "AMZN": "Amazon.com Inc.", "NVDA": "NVIDIA Corporation", "META": "Meta Platforms Inc.",
    "TSLA": "Tesla Inc.", "BRK-B": "Berkshire Hathaway Inc.", "JPM": "JPMorgan Chase & Co.",
    "V": "Visa Inc.", "UNH": "UnitedHealth Group Inc.", "JNJ": "Johnson & Johnson",
    "WMT": "Walmart Inc.", "PG": "Procter & Gamble Co.", "MA": "Mastercard Inc.",
    "HD": "Home Depot Inc.", "XOM": "Exxon Mobil Corporation", "CVX": "Chevron Corporation",
    "ABBV": "AbbVie Inc.", "MRK": "Merck & Co. Inc.", "KO": "Coca-Cola Co.",
    "PEP": "PepsiCo Inc.", "COST": "Costco Wholesale Corp.", "AVGO": "Broadcom Inc.",
    "ADBE": "Adobe Inc.", "CSCO": "Cisco Systems Inc.", "MCD": "McDonald's Corp.",
    "CRM": "Salesforce Inc.", "ACN": "Accenture plc", "NFLX": "Netflix Inc.",
    "AMD": "Advanced Micro Devices Inc.", "TMO": "Thermo Fisher Scientific Inc.",
    "ABT": "Abbott Laboratories", "LIN": "Linde plc", "DHR": "Danaher Corp.",
    "WFC": "Wells Fargo & Co.", "TXN": "Texas Instruments Inc.", "PM": "Philip Morris International",
    "NEE": "NextEra Energy Inc.", "BMY": "Bristol-Myers Squibb Co.", "RTX": "RTX Corp.",
    "UPS": "United Parcel Service Inc.", "ORCL": "Oracle Corp.", "QCOM": "Qualcomm Inc.",
    "HON": "Honeywell International Inc.", "SBUX": "Starbucks Corp.", "LOW": "Lowe's Companies Inc.",
    "IBM": "International Business Machines Corp.", "GE": "General Electric Co.",
    "CAT": "Caterpillar Inc.", "BA": "Boeing Co.", "GS": "Goldman Sachs Group Inc.",
    "MS": "Morgan Stanley", "BLK": "BlackRock Inc.", "AXP": "American Express Co.",
    "DE": "Deere & Co.", "SPGI": "S&P Global Inc.", "PLD": "Prologis Inc.",
    "T": "AT&T Inc.", "VZ": "Verizon Communications Inc.", "INTC": "Intel Corp.",
    "AMGN": "Amgen Inc.", "GILD": "Gilead Sciences Inc.", "MDT": "Medtronic plc",
    "ISRG": "Intuitive Surgical Inc.", "NOW": "ServiceNow Inc.", "UBER": "Uber Technologies Inc.",
    "BKNG": "Booking Holdings Inc.", "LMT": "Lockheed Martin Corp.", "PYPL": "PayPal Holdings Inc.",
    "SYK": "Stryker Corp.", "MDLZ": "Mondelez International Inc.", "ADI": "Analog Devices Inc.",
    "REGN": "Regeneron Pharmaceuticals Inc.", "VRTX": "Vertex Pharmaceuticals Inc.",
    "TJX": "TJX Companies Inc.", "CB": "Chubb Ltd.", "MMC": "Marsh & McLennan Companies Inc.",
    "SCHW": "Charles Schwab Corp.", "CI": "Cigna Group", "ZTS": "Zoetis Inc.",
    "SO": "Southern Co.", "DUK": "Duke Energy Corp.", "PGR": "Progressive Corp.",
    "BSX": "Boston Scientific Corp.", "TMUS": "T-Mobile US Inc.", "FI": "Fiserv Inc.",
    "EOG": "EOG Resources Inc.", "SLB": "Schlumberger Ltd.", "AMAT": "Applied Materials Inc.",
    "MU": "Micron Technology Inc.", "LRCX": "Lam Research Corp.", "KLAC": "KLA Corp.",
    "PANW": "Palo Alto Networks Inc.", "SNPS": "Synopsys Inc.", "CDNS": "Cadence Design Systems Inc.",
    "INTU": "Intuit Inc.", "SHOP": "Shopify Inc.", "ABNB": "Airbnb Inc.",
    "DIS": "Walt Disney Co.", "CMCSA": "Comcast Corp.", "NKE": "Nike Inc.",
    "F": "Ford Motor Co.", "GM": "General Motors Co.", "DAL": "Delta Air Lines Inc.",
    "UAL": "United Airlines Holdings Inc.", "COIN": "Coinbase Global Inc.",
    "PLTR": "Palantir Technologies Inc.", "SMCI": "Super Micro Computer Inc.",
    "ARM": "Arm Holdings plc", "SPY": "SPDR S&P 500 ETF Trust",  # benchmark
}


def get_sp500_tickers() -> dict:
    """
    Try to fetch the live current S&P 500 list from Wikipedia.
    Returns {ticker: company_name}. Falls back to FALLBACK_TICKERS on failure.
    """
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    try:
        import pandas as pd
        from io import StringIO
        from urllib.request import Request, urlopen

        # Wikipedia returns HTTP 403 to bare programmatic requests (no browser
        # User-Agent), which was silently forcing the fallback list. Fetch the
        # page ourselves with a normal User-Agent header, then parse the HTML.
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; stockbacktester/1.0)"})
        with urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8")
        tables = pd.read_html(StringIO(html))

        df = tables[0]
        tickers = {}
        for _, row in df.iterrows():
            symbol = str(row["Symbol"]).strip().replace(".", "-")  # yfinance uses '-' not '.'
            name = str(row["Security"]).strip()
            if symbol and symbol.lower() != "nan":
                tickers[symbol] = name
        if len(tickers) < 400:
            raise ValueError(f"Only parsed {len(tickers)} tickers, expected ~500. Table format may have changed.")
        logger.info(f"Fetched {len(tickers)} live S&P 500 tickers from Wikipedia.")
        return tickers
    except Exception as e:
        logger.warning(f"Could not fetch live S&P 500 list ({type(e).__name__}: {e}). Using fallback snapshot of {len(FALLBACK_TICKERS)} tickers instead.")
        return dict(FALLBACK_TICKERS)


def get_ticker_universe() -> dict:
    """Full universe: S&P 500 (live or fallback) + a benchmark + extra liquid names."""
    universe = get_sp500_tickers()
    # make sure benchmark and a few extra popular non-S&P names are always included
    for extra_ticker, extra_name in FALLBACK_TICKERS.items():
        universe.setdefault(extra_ticker, extra_name)
    return universe
