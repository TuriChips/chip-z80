# synth/ (Leo)
`synth/run.sh` maps each CPU block to `sky130_fd_sc_hd` (typical corner `tt_025C_1v80`, `lpflow_*`/probe/delay cells filtered by `sky130/filter_lib.py`) with Yosys, then OpenSTA (inside OpenROAD, `sta.tcl`) times the mapped netlist. No placement, ideal wires and clock, so the times are gates only. Unlike chip-6502/chip-8080's generic `abc -g` runs, this is PDK-mapped with STA (the 6502's `synth/sky130/` flow without placement). If the liberty file or `openroad` is missing (PR CI has only the models and apt yosys) it prints SKIP, exits 0 and leaves the committed report untouched. Needs `source <toolchain>/scripts/eda-env.sh` (toolchain v0.9, as the Makefile pins).

Output: `synth/report.txt` (cells, flops, latches, area, worst path per block), logs in `synth/logs/<block>.{yosys.log,stat.txt,sta.log}`.

- Blocks: `z80_alu`, `z80_regs`, `z80_timing`. `z80_mem` is a test RAM (blocks.md §1) and is not synthesized.
- Full chip: runs on `TOP` (default `z80`) using `rtl/files.f` when it exists. Until then the report says it was skipped; that is not an error.
- `PERIOD_NS` (default 100) is a stand-in clock: the spec has no electrical timing. Blocks with no `clk` port get a virtual clock (input-to-output paths).
- `BLOCKS="name:dir ..."` overrides the block list.
- `check -assert` runs on each block, so a latch-free, driver-clean netlist is asserted, not just hoped for. Latch column in the report is 0 for all three.
- Not done: full chip, placement and layout (later issue, after C2-C8 pass).
