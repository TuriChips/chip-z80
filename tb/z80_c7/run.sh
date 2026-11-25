#!/bin/sh
# C7 run from the repo root. ./run.sh          -> on the RTL (expect PASS)
#   ./run.sh mutant   -> bus_conflict detector disabled in a private copy of z80_system.v (expect FAIL)
#   ./run.sh memonly  -> sys_drive = mem_rd           (io_rd and inta terms removed; expect FAIL)
#   ./run.sh nointa   -> sys_drive = mem_rd | io_rd   (inta term removed; expect FAIL)
#   ./run.sh noio     -> sys_drive = mem_rd | inta    (io_rd term removed; expect FAIL)
#   ./run.sh nomem    -> sys_drive = io_rd | inta     (mem_rd term removed; expect FAIL)
set -e
M=$1; D=build/z80_c7; [ -n "$M" ] && D=build/z80_c7_$M; rm -rf $D; mkdir -p $D
SYS=rtl/control/z80_system.v
T='wire sys_drive = mem_rd | io_rd | inta;'
case "$M" in
  "") ;;
  mutant) sed 's/if (d_oe && sys_drive) bus_conflict <= 1.b1;/\/\/ detector disabled/' $SYS > $D/z80_system.v; grep -q 'detector disabled' $D/z80_system.v; SYS=$D/z80_system.v ;;
  memonly|nointa|noio|nomem)
    case $M in memonly) R='mem_rd';; nointa) R='mem_rd | io_rd';; noio) R='mem_rd | inta';; nomem) R='io_rd | inta';; esac
    sed "s/$T/wire sys_drive = $R;/" $SYS > $D/z80_system.v; grep -q "wire sys_drive = $R;" $D/z80_system.v; SYS=$D/z80_system.v ;;
  *) echo "unknown mode $M"; exit 2 ;;
esac
verilator --binary --timing -Wno-fatal -Wno-lint -Wno-style --Mdir $D --top tb +incdir+rtl/control \
  rtl/datapath/z80_alu.v rtl/datapath/z80_regs.v rtl/control/z80_timing.v rtl/control/z80_decode.v rtl/control/z80_control.v rtl/top.v \
  rtl/datapath/z80_mem.v $SYS tb/z80_c7/tb.sv >$D/build.log 2>&1 || { tail -20 $D/build.log; exit 1; }
$D/Vtb | tee $D/out.txt; grep -q "^PASS C7" $D/out.txt
