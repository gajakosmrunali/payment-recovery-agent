#!/usr/bin/env bash
# One-time setup: creates a virtual environment and installs dependencies.
# Run from the project root:  bash scripts/setup.sh
set -e

cd "$(dirname "$0")/.."

echo "Creating virtual environment (.venv)..."
python3 -m venv .venv

echo "Activating virtual environment..."
source .venv/bin/activate

echo "Upgrading pip..."
pip install --upgrade pip

echo "Installing dependencies from requirements.txt..."
pip install -r requirements.txt

if [ ! -f ".env" ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
fi

echo ""
echo "Setup complete. Next steps:"
echo "  source .venv/bin/activate"
echo "  python -m src.run_pipeline"
echo "  streamlit run dashboard/app.py"
