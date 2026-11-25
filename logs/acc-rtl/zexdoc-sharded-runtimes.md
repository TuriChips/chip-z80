# Sharded zexdoc: runtime per long group on a GitHub-hosted runner (chip-z80 #78)

Rate measured on the smoke run https://github.com/TuriChips/chip-z80/actions/runs/45527431730 (ubuntu-24.04, 3 groups in parallel):
group 13 = 119,784,198 half-clocks in 65 s = 1.84 M half-clocks/s (our 2-CPU box: 0.28-0.42 M/s, i.e. ~5x slower; its group 13 took 322 s).
Half-clocks per reference instruction: 119,784,198 / 7,352,142 = 16.3 (group 15: 61,390,456 / 3,793,623 = 16.2). Used: 16.2.
Instruction counts: logs/acc-ref/zexdoc-mostek-nmos-summary.log (Beru's `sw/cpm_ref.py --groups`).

| group | ref instructions | half-clocks (x16.2) | hosted runtime @1.84 M/s | @0.40 M/s (our box) | source |
|---|---|---|---|---|---|
| 0 | 279,550,746 | 4.5e9 | 0.7 h | 3.1 h | measured instr, projected time |
| 7 | 637,477,419 | 1.03e10 | 1.6 h | 7.2 h | measured instr, projected time |
| 5 | >= 884,146,176 (ref run hit its 1500 s limit) | >= 1.4e10 | >= 2.2 h (true total unmeasured) | >= 9.9 h | lower bound only |
| 6 | not measured (ref stops at DD 84 until U1-U3) | unknown; same test masks as group 5, so assume the same scale | ~2-3 h (assumption) | | assumption |

All four fit the 6 h cap on a hosted runner if the rate holds (group 5 would need more than 2.7x the lower bound to break it).
They would NOT fit the 6 h cap at our box's speed (7, 5 and probably 6). `--maxclk` is left at its 4e11 default (no silent cap).
Whole run: ~3.5e9 ref instr = 5.7e10 half-clocks = ~8.6 core-hours at the hosted rate; wall time is set by the longest shard (group 5, ~2-3 h).
