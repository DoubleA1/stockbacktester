"""
Convenience launcher: checks whether the database has been built yet,
starts the backend server, and opens your browser to the site.

Usage:
    python run.py
"""

import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).parent
DB_PATH = ROOT / "backend" / "data" / "market.db"


def main():
    if not DB_PATH.exists():
        print("=" * 70)
        print("No database found yet. You need to run the data pipeline first")
        print("to pull real historical prices from Yahoo Finance.")
        print()
        print("This is a ONE-TIME step (a few minutes for ~100 tickers, longer")
        print("for the full ~750-1000 ticker default list). Run:")
        print()
        print("    cd data_pipeline")
        print("    python fetch_data.py --backfill")
        print()
        print("Tip: test with a small slice first to make sure everything works:")
        print("    python fetch_data.py --backfill --limit 20")
        print("=" * 70)
        sys.exit(1)

    print("Starting server at http://localhost:8000 ...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=str(ROOT / "backend"),
    )
    time.sleep(2)
    webbrowser.open("http://localhost:8000")
    print("Opened http://localhost:8000 in your browser. Press Ctrl+C here to stop the server.")
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()


if __name__ == "__main__":
    main()
