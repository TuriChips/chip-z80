#!/usr/bin/env bash
# Nightly: full C8 on the RTL, 64 seeds x 1000 instructions, coverage enforced (C8_COVER=1). ~50 min on one job.
# Zexdoc is NOT run here: it is sharded in .github/workflows/zexdoc.yml (dispatch it by hand: gh workflow run zexdoc.yml -f ref=<commit>).
# Logs in logs/nightly-*/c8-rtl/ (random-c8.log, random-c8-coverage.log); each gets a header with commit, Actions run ID and Verilator version.
set -u
cd "$(git rev-parse --show-toplevel)"
run="logs/nightly-$(date -u +%Y%m%dT%H%M%SZ)"; mkdir -p "$run"
rc=0
make c8-rtl SEEDS=64 INSTR=1000 C8_COVER=1 C8_RUN="$run/c8-rtl" 2>&1 | tee "$run/c8-rtl.log"; [ "${PIPESTATUS[0]}" -eq 0 ] || rc=1
hdr="# commit $(git rev-parse HEAD); Actions run ${GITHUB_RUN_ID:-local}; $(verilator --version 2>&1 | head -1); $(date -u +%Y-%m-%dT%H:%M:%SZ); make c8-rtl SEEDS=64 INSTR=1000 C8_COVER=1; exit $rc"
for f in "$run"/c8-rtl/random-c8.log "$run"/c8-rtl/random-c8-coverage.log; do
  [ -f "$f" ] && { { echo "$hdr"; cat "$f"; } > "$f.tmp" && mv "$f.tmp" "$f"; }
done
exit $rc
