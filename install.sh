#!/usr/bin/env bash
# BraidCord setup: verify the toolchain, install any declared dependency, compile
# and smoke-test the tool, then EXIT. Nothing is started in the foreground.
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "error: python3 is required and was not found on PATH" >&2
    exit 1
fi

"$PYTHON" -c 'import sys
if sys.version_info < (3, 9):
    raise SystemExit("error: BraidCord needs Python 3.9 or newer, found %s" % sys.version.split()[0])'
echo "Python: $("$PYTHON" --version 2>&1)"

if [ -f requirements.txt ] && grep -qvE '^[[:space:]]*(#|$)' requirements.txt; then
    echo "Installing declared dependencies..."
    "$PYTHON" -m pip install --upgrade pip setuptools wheel
    "$PYTHON" -m pip install -r requirements.txt
else
    echo "Dependencies: none (standard library only)"
fi

echo "Compiling braidcord.py..."
"$PYTHON" -m py_compile braidcord.py

echo "Importing the module..."
"$PYTHON" -c 'import braidcord; assert braidcord.pattern_inventory_problems() == []'

echo "Running a smoke test in a temporary store..."
SMOKE_DIR="$(mktemp -d)"
trap 'rm -rf "$SMOKE_DIR"' EXIT
"$PYTHON" braidcord.py --data-dir "$SMOKE_DIR" patterns >/dev/null
"$PYTHON" braidcord.py --data-dir "$SMOKE_DIR" colors add Crimson --hex B3122E >/dev/null
"$PYTHON" braidcord.py --data-dir "$SMOKE_DIR" estimate --pattern round-8 --turns 40 >/dev/null
"$PYTHON" braidcord.py --data-dir "$SMOKE_DIR" colors >/dev/null
rm -rf "$SMOKE_DIR"
trap - EXIT

echo
echo "Setup complete. Nothing is running: BraidCord is a command you invoke."
echo "  python3 braidcord.py --help          # command reference"
echo "  bash demo.sh                         # end-to-end walkthrough in ./demo-data"
echo "  python3 -m unittest discover -s tests -t .    # test suite"
