# Toolchain convention: tb/<block>/files.f = RTL + testbench list, relative to the repo root; top module `tb`.
# RTL: Zura's top lands as rtl/ (file list not settled yet). Replace the next line with `-f rtl/files.f` or the RTL file names when it does.
# Top-module name macro (default z80_top): add +define+Z80_TOP=z80 if the spec-v1 issue settles on `z80`.
-f rtl/files.f
tb/z80_bus/z80_system.sv
tb/z80_bus/tb.sv
