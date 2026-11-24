#!/usr/bin/env bash
# Long acceptance tests (zexdoc: hours). Run by the nightly workflow, never by PR CI.
# Runs `make acceptance` (sw/exerciser/run_rtl.py: prelim + zexdoc on the RTL; logs in logs/acc-rtl/).
# SKIPs cleanly until run_rtl.py exists.
set -u
cd "$(git rev-parse --show-toplevel)"
[ -f sw/exerciser/run_rtl.py ] || { echo "SKIP nightly: sw/exerciser/run_rtl.py not there yet"; exit 0; }
run="logs/nightly-$(date -u +%Y%m%dT%H%M%SZ)"; mkdir -p "$run"
make acceptance 2>&1 | tee "$run/acceptance.log"; exit "${PIPESTATUS[0]}"
