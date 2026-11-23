#!/usr/bin/env bash
# One C8 seed (called by run.sh): generate, get the DUT trace, compare. Prints one PASS/FAIL line.
#   tests/random/seed.sh SEED OUTDIR INSTR
# DUT=ref (default): the reference model replays .hex + .stim (refrun.py), a determinism and replay check.
# DUT=rtl: $RTL_TRACE_CMD HEX STIM OUT.pins runs the RTL testbench and dumps the .pins format (compare.py header).
set -u
seed=$1; out=$2; instr=$3
cd "$(git rev-parse --show-toplevel)"
b="$out/s$seed"
python3 -I -B tests/random/gen.py --seed "$seed" --out "$b" --instr "$instr" >"$b.gen.log" 2>&1 || { echo "FAIL seed $seed: generator ($b.gen.log)"; exit 1; }
if [ "${DUT:-ref}" = rtl ]; then
  ${RTL_TRACE_CMD:?DUT=rtl needs RTL_TRACE_CMD} "$b.hex" "$b.stim" "$b.dut.pins" >"$b.dut.log" 2>&1 || { echo "FAIL seed $seed: RTL run ($b.dut.log)"; exit 1; }
else
  python3 -I -B tests/random/refrun.py --hex "$b.hex" --stim "$b.stim" --out "$b.dut" >"$b.dut.log" 2>&1 || { echo "FAIL seed $seed: replay ($b.dut.log)"; exit 1; }
fi
if python3 -I -B tests/random/compare.py "$b.pins" "$b.dut.pins" --idx "$b.idx" >"$b.cmp.log" 2>&1; then
  echo "PASS seed $seed: $(head -1 "$b.gen.log" | sed 's/^seed [0-9]* //'); $(cat "$b.cmp.log")"
else
  echo "FAIL seed $seed: $(tr '\n' ' ' <"$b.cmp.log")"; exit 1
fi
