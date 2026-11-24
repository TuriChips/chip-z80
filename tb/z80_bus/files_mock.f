# Harness self-test: no RTL, the expected vectors are replayed as a perfect DUT. Not a toolchain target (files.f is).
#   verilator --binary --timing -Wall --Mdir build/z80_bus_mock -f tb/z80_bus/files_mock.f --top tb && build/z80_bus_mock/Vtb [+MUTATE=<half>]
+define+Z80_MOCK
tb/z80_bus/z80_system.sv
tb/z80_bus/tb.sv
