#!/bin/bash
# Double-click on a Mac to start the transect tool.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "First run: setting up (needs internet, takes a minute)..."
  python3 -m venv .venv || { echo "Python 3 is needed: https://www.python.org/downloads/"; read -p "Press Enter"; exit 1; }
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt || { echo "Install failed"; read -p "Press Enter"; exit 1; }
fi
exec .venv/bin/python app.py
