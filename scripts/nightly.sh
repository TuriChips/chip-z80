#!/usr/bin/env bash
# Long tests: full C8 on the RTL, then acceptance (zexdoc: hours). Run by the nightly workflow, never by PR CI.
# C8: `make c8-rtl SEEDS=64 INSTR=1000` (the default SEEDS=8 is the quick local run; PR CI does not run it); logs in logs/nightly-*/c8-rtl/.
# Acceptance: `make acceptance` (sw/exerciser/run_rtl.py: prelim + zexdoc on the RTL; logs in logs/acc-rtl/), SKIPs until it exists.
set -u
cd "$(git rev-parse --show-toplevel)"
run="logs/nightly-$(date -u +%Y%m%dT%H%M%SZ)"; mkdir -p "$run"
rc=0
make c8-rtl SEEDS=64 INSTR=1000 C8_RUN="$run/c8-rtl" 2>&1 | tee "$run/c8-rtl.log"; [ "${PIPESTATUS[0]}" -eq 0 ] || rc=1
if [ -f sw/exerciser/run_rtl.py ]; then
  make acceptance 2>&1 | tee "$run/acceptance.log"; [ "${PIPESTATUS[0]}" -eq 0 ] || rc=1
else echo "SKIP acceptance: sw/exerciser/run_rtl.py not there yet"; fi
exit $rc
