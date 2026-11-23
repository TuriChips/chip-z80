#!/usr/bin/env bash
# Long acceptance tests (zexdoc: hours). Run by the nightly workflow, never by PR CI.
# Convention: tests/acceptance/run.sh (owned by verification) fetches what it needs via
# scripts/fetch_thirdparty.sh and exits non-zero on failure. SKIPs cleanly until it exists.
set -u
cd "$(git rev-parse --show-toplevel)"
[ -f tests/acceptance/run.sh ] || { echo "SKIP nightly: tests/acceptance/run.sh not there yet"; exit 0; }
run="logs/nightly-$(date -u +%Y%m%dT%H%M%SZ)"; mkdir -p "$run"
RUN_DIR="$run" bash tests/acceptance/run.sh 2>&1 | tee "$run/acceptance.log"; exit "${PIPESTATUS[0]}"
