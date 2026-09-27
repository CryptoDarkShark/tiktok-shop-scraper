#!/bin/bash
# Re-export brands_1000.xlsx every 20 minutes while the b1000 pipeline runs; commit + push when it changes.
cd "$(dirname "$0")/.." || exit 1
running() { ps -eo cmd | grep -E "[p]ipeline/b1000.py (enrich|signals|resolve|serp)" >/dev/null; }
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
while running; do sleep 1200; publish; done
publish
echo "pipeline finished; final export done"
