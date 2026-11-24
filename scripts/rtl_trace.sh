#!/usr/bin/env bash
# RTL trace for C8 (chip-z80#63): the RTL_TRACE_CMD that tests/random/seed.sh calls under DUT=rtl.
#   scripts/rtl_trace.sh HEX STIM OUT.pins
# Builds tb/z80_bus (Titus's bench, top module tb, RTL from rtl/files.f) once with Verilator into build/rtl_trace/obj
# (rebuilt only when an RTL/tb file is newer; flock makes parallel seeds wait for one build), then runs the one case
# the generator wrote next to HEX (<base>.vec/ + <base>.case, the bench's own packing) and moves the bench's +TRACE dump
# to OUT.pins. The bench's own exp/mask compare is the generator's trace again, so its FAIL lines are informative only:
# the verdict is compare.py's, run by seed.sh. Exit 1 only if the build or the run itself failed.
set -eu
[ $# -eq 3 ] || { echo "usage: $0 HEX STIM OUT.pins" >&2; exit 2; }
hex=$1; out=$3
cd "$(git rev-parse --show-toplevel)"
hex=$(realpath "$hex"); out=$(realpath -m "$out")
base=${hex%.hex}; name=$(basename "$base")
[ -d "$base.vec" ] && [ -f "$base.case" ] || { echo "no $base.vec/ or $base.case (gen.py writes them)" >&2; exit 1; }
obj=build/rtl_trace/obj; mkdir -p build/rtl_trace
(
  flock 9
  if [ ! -x "$obj/Vtb" ] || [ -n "$(find rtl tb/z80_bus scripts/rtl_trace.sh -type f \( -name '*.v' -o -name '*.sv' -o -name '*.vh' -o -name '*.f' -o -name rtl_trace.sh \) -newer "$obj/Vtb" -print -quit)" ]; then
    verilator --binary --timing -Wno-fatal -Wno-lint -Wno-style -O1 --x-assign unique --x-initial unique \
      --top-module tb -Mdir "$obj" -o Vtb -f tb/z80_bus/files.f >build/rtl_trace/build.log 2>&1 \
      || { echo "verilator build failed, see build/rtl_trace/build.log" >&2; tail -20 build/rtl_trace/build.log >&2; exit 1; }
  fi
) 9>build/rtl_trace/lock
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
"$obj/Vtb" +VECROOT="$(dirname "$base")/" +VECSUF=.vec +CASES="$base.case" +TRACE="$tmp/t" >"$tmp/run.log" 2>&1 || { cat "$tmp/run.log"; exit 1; }
tail -3 "$tmp/run.log"
[ -s "$tmp/t.$name.txt" ] || { echo "no trace written" >&2; cat "$tmp/run.log" >&2; exit 1; }
{ echo "# z80-pintrace v2: RTL (scripts/rtl_trace.sh, tb/z80_bus +TRACE)"; cat "$tmp/t.$name.txt"; } >"$out"
