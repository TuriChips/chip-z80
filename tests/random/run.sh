#!/usr/bin/env bash
# C8 random tests (Beru, chip-z80#8), run by the toolchain's `make test` (convention: chip-6502#52; RUN_DIR set by
# scripts/run_tests.sh, logs written as $RUN_DIR/random-*.log, one PASS/FAIL line per step, exit 1 on any FAIL).
#   1. ref/refz80 and ref/pinsz80 self-tests
#   1b. cross-check of the pin model against Titus's directed bus vectors (tests/z80_bus/vectors), once they exist
#   2. C8: SEEDS seeds. Each makes a random program + WAIT/INT/NMI/BUSRQ stimulus (spec §7 C8, §8.4), the reference
#      model's expected pin trace, the DUT trace, and compares every pin in every half T state.
#   2b. decode-xcheck: simulated rtl/control/z80_decode.v vs the pin model's M-cycle layouts (xcheck_decode.py, #39)
#   3. coverage: executed count per documented form (850 minus the excluded set), stimulus kinds hit.
# DUT=ref (default, until RTL exists): the DUT trace is the reference model replaying the image and stimulus alone.
# DUT=rtl RTL_TRACE_CMD='scripts/rtl_trace.sh': the one-line switch. The command gets HEX STIM OUT.pins and must
#   write the .pins format (tests/random/compare.py documents it).
# Knobs: SEEDS (64) INSTR (1000 instructions per seed) JOBS (4) FIRST (first seed, 1).
set -u
cd "$(git rev-parse --show-toplevel)"
run="${RUN_DIR:-logs/$(date -u +%Y%m%dT%H%M%SZ)}"; mkdir -p "$run"
SEEDS=${SEEDS:-64}; INSTR=${INSTR:-1000}; JOBS=${JOBS:-4}; FIRST=${FIRST:-1}
export DUT=${DUT:-ref}
ok=0
step() { # name log cmd...   PASS needs a line starting PASS and none starting FAIL/DIFF
  local name=$1 log=$2; shift 2
  if "$@" >"$log" 2>&1 && grep -q '^PASS' "$log" && ! grep -q -E '^(FAIL|DIFF)' "$log"; then echo "PASS $name"; else echo "FAIL $name ($log)"; ok=1; fi
}
py() { python3 -I -B "$@"; }
if py ref/test_refz80.py >"$run/random-ref-selftest.log" 2>&1 && grep -q -E '^[0-9]+ tests passed' "$run/random-ref-selftest.log" && ! grep -q -E '^(FAIL|Traceback)' "$run/random-ref-selftest.log"; then echo "PASS ref-selftest"; else echo "FAIL ref-selftest ($run/random-ref-selftest.log)"; ok=1; fi
step pins-selftest  "$run/random-pins-selftest.log" py ref/test_pinsz80.py
if [ -f tests/z80_bus/vectors/cases.txt ]; then
  step bus-xcheck "$run/random-bus-xcheck.log" py tests/random/xcheck_bus.py
else
  echo "SKIP bus-xcheck (tests/z80_bus/vectors not in the tree yet: chip-z80 PR #12)"
fi
if [ -f rtl/control/z80_decode.v ] && command -v verilator >/dev/null; then
  step decode-xcheck "$run/random-decode-xcheck.log" py tests/random/xcheck_decode.py
else
  echo "SKIP decode-xcheck (rtl/control/z80_decode.v or verilator missing)"
fi
out="build/c8"; rm -rf "$out"; mkdir -p "$out"
seq "$FIRST" $((FIRST + SEEDS - 1)) | xargs -P "$JOBS" -I{} tests/random/seed.sh {} "$out" "$INSTR" >"$run/random-c8-seeds.unsorted" 2>&1
sort -k3,3n -t' ' "$run/random-c8-seeds.unsorted" >"$run/random-c8.log"; rm -f "$run/random-c8-seeds.unsorted"
nf=$(grep -c '^FAIL' "$run/random-c8.log"); np=$(grep -c '^PASS' "$run/random-c8.log")
echo "C8 (DUT=$DUT): $np/$SEEDS seeds pass, $INSTR instructions per seed, $nf fail"
[ "$nf" -eq 0 ] && [ "$np" -eq "$SEEDS" ] && echo "PASS c8" >>"$run/random-c8.log" || { echo "FAIL c8 ($run/random-c8.log)"; ok=1; }
step coverage "$run/random-c8-coverage.log" py tests/random/cover.py "$out"/s*.cov.json
[ "$ok" -eq 0 ] && echo "PASS random" || echo "FAIL random"
exit $ok
