#!/usr/bin/env bash
# Refresh the local market database with the latest daily prices.
# Intended to be run on a schedule (cron) on the Raspberry Pi.
set -euo pipefail

# Resolve the project root regardless of where cron invokes this from.
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$PROJECT/data_pipeline"
"$PROJECT/.venv/bin/python" fetch_data.py --update

echo "[$(date -Is)] data update complete"
