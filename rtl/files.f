# RTL of the Z80 CPU, paths relative to the repo root (toolchain convention). Top module: z80 (rtl/top.v).
# z80_system (rtl/control/z80_system.v, system wrapper + CP/M stub) is NOT listed: simulation only, never synthesized (TOP stays z80).
+incdir+rtl/control
rtl/datapath/z80_alu.v
rtl/datapath/z80_regs.v
rtl/control/z80_timing.v
rtl/control/z80_decode.v
rtl/control/z80_control.v
rtl/top.v
