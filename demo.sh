#!/usr/bin/env bash
# Walk BraidCord end to end against ./demo-data. Non-interactive, exits when done.
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
DATA_DIR="${BRAIDCORD_DEMO_DIR:-./demo-data}"

rm -rf "$DATA_DIR"

run() {
    printf '$ braidcord %s\n' "$*"
    "$PYTHON" braidcord.py --data-dir "$DATA_DIR" "$@"
    printf '\n'
}

# Allow a command that is expected to fail without ending the demo.
run_expected_failure() {
    printf '$ braidcord %s\n' "$*"
    "$PYTHON" braidcord.py --data-dir "$DATA_DIR" "$@" || true
    printf '\n'
}

echo "== BraidCord demo (store: $DATA_DIR) =="
echo

run patterns
run pattern round-8
run colors
run colors add Crimson --hex B3122E --brand Silk
run colors add Navy --hex 1B2A4A --brand Silk
run colors add Gold --hex C9A227
run colors add Slate --hex 4A5568 --notes "recycled sari silk"
run colors add "Sea Glass" --hex 8FBFB3 --brand Linen
run colors
run setups

run setup save belt --pattern round-8 \
    --slot 1=Crimson --slot 5=Navy --slot 9=Gold --slot 13=Slate \
    --slot 17=Crimson --slot 21=Gold --slot 25=Slate --slot 29=Navy
run setup save wristlet --pattern spiral-8 \
    --slot 1=Crimson --slot 5=Gold --slot 9=Crimson --slot 13=Gold \
    --slot 17=Crimson --slot 21=Gold --slot 25=Crimson --slot 29=Gold

cuff=(setup save cuff --pattern flat-16)
palette=(Crimson Navy Gold Slate "Sea Glass")
index=0
for slot in 1 2 3 4 5 6 7 8 17 18 19 20 21 22 23 24; do
    cuff+=(--slot "$slot=${palette[$((index % 5))]}")
    index=$((index + 1))
done
run "${cuff[@]}"

run setups
run setup belt --turns 40
run setup belt --turns 40 --imperial
run setup cuff --length 70
run estimate --pattern round-8 --turns 40
run estimate --pattern square-8 --turns 120 --imperial
run estimate --pattern round-8 --length 60
run estimate --pattern round-8 --length 8 --imperial

echo "== deliberate failures (each is one error line, exit 2) =="
echo
run_expected_failure estimate --pattern round-8 --turns 0
run_expected_failure pattern nope
run_expected_failure colors rm gold
run_expected_failure setup save belt --pattern round-8 --slot 1=Crimson
run_expected_failure setup save belt --pattern round-8 --slot 40=Crimson

run colors add "Test Swatch" --hex 8C8C8C --notes "added only to show removal"
run colors rm "Test Swatch"
run setup rm wristlet
run setups
run colors

echo "== demo complete: state is in $DATA_DIR/braidcord.json =="
