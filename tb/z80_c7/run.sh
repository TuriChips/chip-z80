#!/bin/sh
# C7 run from the repo root. ./run.sh        -> on the RTL (expect PASS)
#                            ./run.sh mutant -> bus_conflict detector disabled in a private copy of z80_system.v (expect FAIL)
set -e
D=build/z80_c7; [ "$1" = mutant ] && D=build/z80_c7_mutant; rm -rf $D; mkdir -p $D
SYS=rtl/control/z80_system.v
if [ "$1" = mutant ]; then sed 's/if (d_oe && sys_drive) bus_conflict <= 1.b1;/\/\/ detector disabled/' $SYS > $D/z80_system.v; grep -q 'detector disabled' $D/z80_system.v; SYS=$D/z80_system.v; fi
verilator --binary --timing -Wno-fatal -Wno-lint -Wno-style --Mdir $D --top tb +incdir+rtl/control \
  rtl/datapath/z80_alu.v rtl/datapath/z80_regs.v rtl/control/z80_timing.v rtl/control/z80_decode.v rtl/control/z80_control.v rtl/top.v \
  rtl/datapath/z80_mem.v $SYS tb/z80_c7/tb.sv >$D/build.log 2>&1 || { tail -20 $D/build.log; exit 1; }
$D/Vtb | tee $D/out.txt; grep -q "^PASS C7" $D/out.txt
