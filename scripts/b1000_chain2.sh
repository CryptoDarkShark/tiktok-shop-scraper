#!/bin/bash
# After the current b1000 run: lookalike expansion -> resolve -> enrich -> signals, refreshing brands_1000.xlsx throughout.
cd "$(dirname "$0")/.." || exit 1
touch data/b1000/RUNNING
publish() {
  python3 pipeline/b1000.py output > data/b1000/last_export.log 2>&1 || return
  if ! git diff --quiet -- brands_1000.xlsx; then
    git commit -q -m "brands_1000.xlsx: automatic progress export ($(date -u +%Y-%m-%dT%H:%MZ))

$(head -1 data/b1000/last_export.log)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015V3tpdvHrRGbX5pxPwM4Y2" -- brands_1000.xlsx && git push -q origin claude/trusting-mayer-4s23s5
    echo "$(date -u +%H:%M) exported: $(head -1 data/b1000/last_export.log)"
  fi
}
( while [ -f data/b1000/RUNNING ]; do sleep 1200; [ -f data/b1000/RUNNING ] && publish; done ) &
while ps -eo cmd | grep -E "[p]ipeline/b1000.py (enrich|signals|resolve|serp|awards)" >/dev/null; do sleep 60; done
publish
python3 -u pipeline/b1000.py lookalike
python3 -u pipeline/b1000.py resolve --workers 24
python3 -u pipeline/b1000.py enrich --workers 24
python3 -u pipeline/b1000.py signals --workers 16
rm -f data/b1000/RUNNING
publish
echo "chain2 finished"
