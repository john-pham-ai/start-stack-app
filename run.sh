#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ ! -d venv ]; then
  echo "Setting up virtual environment..."
  if ! python3 -m venv venv; then
    echo "Failed to create virtual environment. You may need: sudo apt install python3-venv" >&2
    exit 1
  fi
fi

./venv/bin/pip install -q -r requirements.txt

exec ./venv/bin/python app.py
