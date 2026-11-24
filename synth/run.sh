#!/usr/bin/env bash
# Leo: sky130 (sky130_fd_sc_hd, tt_025C_1v80) synthesis of each Z80 block, and of the full chip once rtl/files.f exists.
# Usage: source <toolchain>/scripts/eda-env.sh; synth/run.sh      -> synth/report.txt, synth/logs/<block>.{yosys.log,stat.txt,sta.log}
# Env: TOP (default z80), PERIOD_NS (default 100 = 10 MHz target, a stand-in: the spec has no electrical timing), BLOCKS=list.
# z80_mem is a test RAM (blocks.md §1) and is never synthesized. No placement or wire load: timing is gates only.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
LIB0=${PDK_ROOT:-/nonexistent}/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
if [ ! -f "$LIB0" ] || ! command -v openroad >/dev/null || ! command -v yosys >/dev/null; then
  echo "SKIP: sky130 liberty, openroad or yosys not available (needs the layout tools: toolchain install_layout_tools.sh, then source scripts/eda-env.sh). Committed synth/report.txt and logs left untouched."
  exit 0
fi
D=synth; L=$D/logs; mkdir -p $L; W=$(mktemp -d); trap 'rm -rf $W' EXIT
TOP=${TOP:-z80}; PERIOD_NS=${PERIOD_NS:-100}; export PERIOD_NS
S=$PDK_ROOT/sky130A/libs.ref/sky130_fd_sc_hd
# CI (toolchain v0.9) fetches only the sky130 Verilog models and has no openroad: skip cleanly, keep the committed report.
# Needs from the toolchain (issue for Tesla): the liberty file and openroad/sta. Local runs use eda-env.sh and are unaffected.
[ -f "$S/lib/sky130_fd_sc_hd__tt_025C_1v80.lib" ] || { echo "synth: SKIP, liberty not found under $S/lib (CI has only the Verilog models). Committed synth/report.txt is from a local run."; exit 0; }
command -v openroad >/dev/null || { echo "synth: SKIP, openroad (OpenSTA) not installed. Committed synth/report.txt is from a local run."; exit 0; }
python3 -I $D/sky130/filter_lib.py $S/lib/sky130_fd_sc_hd__tt_025C_1v80.lib $W/f.lib > $L/filter_lib.log
# name:file[,file...] (first file is the top module's; z80_control instantiates z80_decode, so it takes both)
BLOCKS=${BLOCKS:-"z80_alu:rtl/datapath/z80_alu.v z80_regs:rtl/datapath/z80_regs.v z80_timing:rtl/control/z80_timing.v z80_control:rtl/control/z80_control.v,rtl/control/z80_decode.v"}

run_one() { # name file-list
  local n=$1; shift; local src="$*"
  yosys -l $L/$n.yosys.log -q -p "read_liberty -lib $W/f.lib; read_verilog -I rtl/control $src;
   hierarchy -check -top $n; proc; flatten; opt; wreduce; alumacc; opt; memory -nomap -nordff; memory_map; opt -full; techmap; opt -fast;
   dfflegalize -cell \$_DFF_P_ 01 -cell \$_DLATCH_P_ x;
   dfflibmap -liberty $W/f.lib; abc -D $((PERIOD_NS*1000)) -liberty $W/f.lib; opt_clean -purge; check -assert;
   tee -o $L/$n.stat.txt stat -liberty $W/f.lib; write_verilog -noattr -noexpr $W/$n.v"
  TOP=$n LIB=$W/f.lib NETLIST=$W/$n.v openroad -no_init -exit $D/sta.tcl > $L/$n.sta.log 2>&1
}

{
echo "Z80 synthesis, sky130_fd_sc_hd tt_025C_1v80, yosys $(yosys -V | cut -d' ' -f2), clock $PERIOD_NS ns, ideal wires. Toolchain $(sed -n "s/^TOOLCHAIN_REF ?= *//p" Makefile) (Makefile pin); RTL = main $(git rev-parse --short HEAD)."
printf '%-12s %7s %6s %6s %11s  %s\n' block cells flops latch area_um2 "worst path: data arrival ns (slack)"
} > $W/head
: > $W/rows
row() { # name -> table row from its logs
  local n=$1 st=$L/$1.stat.txt
  local cells flops lat area arr slack
  cells=$(awk '/Number of cells/{print $NF; exit}' $st)
  flops=$(awk '/__(dfxtp|dfrtp|dfstp|dfxbp|dfrbp|dfbbp)/{s+=$NF} END{print s+0}' $st)
  lat=$(awk '/__(dlx|dlr)/{s+=$NF} END{print s+0}' $st)
  area=$(awk '/Chip area/{print $NF}' $st)
  arr=$(awk '/data arrival time/{print $1; exit}' $L/$n.sta.log)
  slack=$(awk '/slack/{print $1; exit}' $L/$n.sta.log)
  printf '%-12s %7s %6s %6s %11s  %s (slack %s at %s ns)\n' $n "$cells" "$flops" "$lat" "$area" "${arr:-n/a}" "${slack:-n/a}" $PERIOD_NS
}
for b in $BLOCKS; do
  n=${b%%:*}; files=${b#*:}
  run_one $n ${files//,/ }
  row $n >> $W/rows
done
: > $W/full
if [ -f rtl/files.f ]; then
  # +incdir+ lines in files.f are handled by -I rtl/control in run_one; everything else is a source file
  run_one $TOP $(grep -v '^\s*\(#\|//\|+\|$\)' rtl/files.f | tr '\n' ' ')
  row $TOP >> $W/full
fi
{
cat $W/head $W/rows
echo
if [ -f rtl/files.f ]; then
  echo "== full chip (rtl/files.f, top $TOP, check -assert held)"
  cat $W/full
else
  echo "== full chip $TOP: skipped, rtl/files.f does not exist"
fi
echo
echo "== warnings"; grep -H -i 'warning' $L/*.yosys.log | sed 's|^synth/logs/||; s|\.yosys\.log:|: |' | grep -v -e 'combinational (run' -e 'unsupported expression' || echo none
} | tee $D/report.txt
