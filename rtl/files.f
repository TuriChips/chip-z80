# RTL of the Z80 CPU, paths relative to the repo root (toolchain convention). Top module: z80 (rtl/top.v).
# z80_system (system wrapper, console/CP/M stub) is added here when it lands.
+incdir+rtl/control
rtl/datapath/z80_alu.v
rtl/datapath/z80_regs.v
rtl/control/z80_timing.v
rtl/control/z80_decode.v
rtl/control/z80_control.v
rtl/top.v
