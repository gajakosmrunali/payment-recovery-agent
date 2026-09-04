#!/usr/bin/env bash
# Runs the full pipeline (fresh data) then launches the dashboard.
# Run from the project root:  bash scripts/run_demo.sh
set -e

cd "$(dirname "$0")/.."
source .venv/bin/activate

echo "Running the recovery agent pipeline..."
python -m src.run_pipeline --regenerate

echo ""
echo "Launching dashboard at http://localhost:8501 ..."
streamlit run dashboard/app.py
