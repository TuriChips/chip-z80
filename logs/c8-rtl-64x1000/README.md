Release evidence for spec §7 C8: full-size random run on the RTL.
Source: nightly run https://github.com/TuriChips/chip-z80/actions/runs/45571712441 (commit 8baefb1, merge of #92), artifact `nightly-logs`.
`make c8-rtl SEEDS=64 INSTR=1000 C8_COVER=1`, exit 0. RTL unchanged since that commit (`git log 8baefb1..main -- rtl/` is empty at commit time).
- c8-rtl-stdout.log: line 6 `C8 (DUT=rtl): 64/64 seeds pass, 1000 instructions per seed, 0 fail`; ends `PASS coverage`.
- random-c8.log: per-seed results (64 PASS), header with commit, run ID, Verilator version, exit 0.
- random-c8-coverage.log: coverage table, ends `PASS coverage`.
