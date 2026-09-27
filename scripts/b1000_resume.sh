#!/bin/bash
# Resume brands_1000 after the caches were lost: restore from brands_1000.xlsx, re-check kept brands, then grow
# with free sources (awards, lookalike rounds) and SerpAPI (30 searches kept in reserve). brands_1000.xlsx is
# re-exported every 20 minutes and pushed when it changes; each 200 main-list brands is noted in milestones.log.
cd "$(dirname "$0")/.." || exit 1
mkdir -p data/b1000
touch data/b1000/RUNNING
publish() {
  [ -f data/b1000/FIRST_PASS_DONE ] || return  # until kept brands are re-checked, an export would lose them
  python3 pipeline/b1000.py output > data/b1000/last_export.log 2>&1 || return
  n=$(sed -n 's/^main list: \([0-9]*\) written.*/\1/p' data/b1000/last_export.log)
  prev=$(cat data/b1000/milestone 2>/dev/null || echo 0)
  if [ -n "$n" ] && [ $((n / 200)) -gt "$prev" ]; then
    echo $((n / 200)) > data/b1000/milestone
    { echo "MILESTONE $((n / 200 * 200)) at $(date -u +%H:%MZ)"; cat data/b1000/last_export.log; echo; } >> data/b1000/milestones.log
  fi
  if ! git diff --quiet -- brands_1000.xlsx; then
    git commit -q -m "brands_1000.xlsx: automatic progress export ($(date -u +%Y-%m-%dT%H:%MZ))

$(head -1 data/b1000/last_export.log)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CziznoytHKLtNR6XV1tNPE" -- brands_1000.xlsx \
      && { git pull -q --no-rebase origin claude/trusting-mayer-4s23s5; git push -q origin claude/trusting-mayer-4s23s5; }
    echo "$(date -u +%H:%M) exported: $(head -1 data/b1000/last_export.log)"
  fi
}
( while [ -f data/b1000/RUNNING ]; do sleep 1200; [ -f data/b1000/RUNNING ] && publish; done ) &
[ -f data/b1000/names.json ] || python3 -u pipeline/b1000.py restore
stage() { python3 -u pipeline/b1000.py resolve --workers 24; python3 -u pipeline/b1000.py enrich --workers 24
          python3 -u pipeline/b1000.py signals --workers 16; publish; }
stage
touch data/b1000/FIRST_PASS_DONE; publish
python3 -u pipeline/b1000.py awards; stage
for round in 1 2 3; do python3 -u pipeline/b1000.py lookalike; stage; done
python3 -u pipeline/b1000.py serp --reserve 30; stage
python3 -u pipeline/b1000.py lookalike; stage
rm -f data/b1000/RUNNING
publish
echo "resume finished"
