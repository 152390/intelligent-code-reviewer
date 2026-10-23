#!/usr/bin/env bash
# Builds the ICR-Reviewer executables on Linux or macOS.
set -e
cd "$(dirname "$0")"
python3 -m venv .venv-build
source .venv-build/bin/activate
pip install --upgrade pip
pip install -r requirements-app.txt pyinstaller
python build.py
echo "SUCCESS. The program is in: $(pwd)/dist/ICR-Reviewer"
