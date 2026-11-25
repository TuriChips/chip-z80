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

## Measured: first full 67-group run (chip-z80 #80)

Run https://github.com/TuriChips/chip-z80/actions/runs/45534465163 (rtl 59dc956, 2026-11-25 08:09 IST start), merged log `logs/acc-rtl/zexdoc-baseline-59dc956.log`: 67/67 OK, 0 timeouts, 0 bus conflicts.
Job wall time = GitHub job start to end (includes ~1 min apt/checkout setup). Group wall s and half-clocks are from the baseline log.

| job | groups | job wall | group half-clocks | note |
|---|---|---|---|---|
| g05 | 5 | 3 h 08 min | 4.00e10 | the critical path; replaces the ">= 2.2 h lower bound" |
| g06 | 6 | 1 h 37 min | 2.03e10 | was an assumption of 2-3 h |
| g07 | 7 | 41 min | 1.02e10 | projected 1.6 h; real was faster |
| g00 | 0 | 19 min | 4.52e9 | |
| g12 | 12 | 17 min | 2.2e9 | |
| g01, g02, g03, g04, g09 | 1,2,3,4,9 | 9-12 min each (g01 12, g09 12, g02 11, g03 9, g04 9) | ~2.2-2.6e9 | |
| batch1 | 10,11,56,57,61 | 6 min | | |
| batch2 | 8,13,14,16,17,19,20,24,25,27,49,58 | 5 min | | |
| batch3 | 15,18,21-23,26,32-47,51-55,... | 2 min | | |
| batch4 | 28-31,48,50,59,60 (decision 9) | 3 min | | |
| merge | | 12 s | | |

Whole run: wall 3 h 08 min (set by group 5), and the merged log appeared at 11:17 IST.
No job came near the 6 h cap; the longest (group 5) used 53% of it. Group 5 ran at 40.0e9 half-clocks / 11,214 s = 3.57 M half-clocks/s inside the job (the earlier 1.84 M/s smoke rate was conservative, since 3 groups shared a runner).
Group 5 therefore holds ~2.47e9 ref instructions (40.0e9 / 16.2), 2.8 x the old lower bound of 884 M; the 6 h cap leaves about 1.9 x headroom, so no split is needed now. If a future RTL change slows group 5 beyond ~1.9 x, split by test vector range (needs a runner change); do not raise --maxclk silently.
