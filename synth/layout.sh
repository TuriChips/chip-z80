#!/usr/bin/env bash
# Leo: sky130 layout of the full Z80: Yosys map -> OpenROAD floorplan/place/CTS/route -> KLayout GDS + PNG.
# Usage: source <toolchain>/scripts/eda-env.sh; synth/layout.sh   -> synth/layout/{z80.def,z80.gds,layout.png}, logs in synth/logs/layout.*
# Env: TOP (z80), PERIOD_NS (100, stand-in: the spec has no electrical timing), UTIL (core utilization %, 25), PLACE_DENSITY (0.45), ROUTE_ITERS (64).
# Needs openroad, klayout, yosys and the sky130 liberty/LEF/GDS; prints SKIP otherwise (CI has none of them yet).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
S=${PDK_ROOT:-/nonexistent}/sky130A/libs.ref/sky130_fd_sc_hd
for t in openroad klayout yosys; do command -v $t >/dev/null || { echo "layout: SKIP, $t not installed. Committed synth/layout/ and logs left untouched."; exit 0; }; done
[ -f $S/gds/sky130_fd_sc_hd.gds ] || { echo "layout: SKIP, sky130 GDS not found under $S"; exit 0; }
D=synth/layout; L=synth/logs; mkdir -p $L; W=$(mktemp -d); trap 'rm -rf $W' EXIT
TOP=${TOP:-z80}; ROUTE_ITERS=${ROUTE_ITERS:-64}; PLACE_DENSITY=${PLACE_DENSITY:-0.45}; export ROUTE_ITERS PLACE_DENSITY; PERIOD_NS=${PERIOD_NS:-100}; UTIL=${UTIL:-25}; export TOP PERIOD_NS UTIL
python3 -I synth/sky130/filter_lib.py $S/lib/sky130_fd_sc_hd__tt_025C_1v80.lib $W/f.lib > $L/layout.filter_lib.log
SRC=$(grep -v '^\s*\(#\|//\|+\|$\)' rtl/files.f | tr '\n' ' ')
# same Yosys recipe as run.sh (full chip)
yosys -l $L/layout.yosys.log -q -p "read_liberty -lib $W/f.lib; read_verilog -I rtl/control $SRC;
 hierarchy -check -top $TOP; proc; flatten; opt; wreduce; alumacc; opt; memory -nomap -nordff; memory_map; opt -full; techmap; opt -fast;
 dfflegalize -cell \$_DFF_P_ 01 -cell \$_DLATCH_P_ x;
 dfflibmap -liberty $W/f.lib; abc -D $((PERIOD_NS*1000)) -liberty $W/f.lib; opt_clean -purge; check -assert;
 tee -o $L/layout.stat.txt stat -liberty $W/f.lib; write_verilog -noattr -noexpr $W/${TOP}.v"
TOP=$TOP OUT=$W NETLIST=$W/${TOP}.v LIB=$W/f.lib openroad -no_init -exit $D/flow.tcl 2>&1 | grep --line-buffered -v Nesterov > $L/layout.openroad.log
cp $W/${TOP}.def $D/${TOP}.def; cp $W/route_drc.rpt $L/layout.route_drc.rpt
klayout -b -r $D/render.py -rd def=$D/${TOP}.def -rd gds=$D/${TOP}.gds -rd png=$D/layout.png -rd top=$TOP -rd pdk=$PDK_ROOT/sky130A > $L/layout.klayout.log 2>&1
echo "DRC (router) violations: $(grep -c violation $L/layout.route_drc.rpt || true)"
