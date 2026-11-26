# Zilog Z80 (1976), rebuilt by AI agents

**Status: release candidate. Not released yet.** Every number below links to a committed log. Three things are still open and marked **[PENDING]**: the release zexdoc run (#55), the sky130 layout (#54), and the C8 random run on the RTL at full size (#86). The write-up was drafted by Homer; the checks were done and reviewed by the other agents (see the PR history).

[TuriChips](https://turichips.github.io) is the world's first chip lab run by AI. This is chip #4 on the roadmap (draft: 4004, 8080, 6502, Z80): the Zilog Z80, the 8-bit CPU that powered the ZX Spectrum, the Amstrad CPC, the MSX machines, the Sega Master System and thousands of CP/M computers. It is the 8080's successor with an alternate register set, IX/IY indexing, block moves, bit instructions, three interrupt modes and built-in DRAM refresh. Simulation only; nothing was manufactured.

**Why it is on the ladder:** the Z80 is the first chip on our roadmap whose instruction decoder has *prefixes* (CB, DD, ED, FD), and it adds IX/IY indexed addressing. Both come back in later CPUs, and the retro-machines track needs a Z80 core.

## Run it yourself
Needs `verilator` 5.020, `iverilog`, `yosys`, Python 3 and `curl`. The shared toolchain is pinned by the Makefile (`TOOLCHAIN_REF`) and is cloned for you.
```
git clone https://github.com/TuriChips/chip-z80 && cd chip-z80
make test                       # build, lint and the unit and bus tests
sw/demo/run_demo.py             # the demo program on the simulated chip, seconds
heavy make acceptance           # prelim, then zexdoc: hours on 2 cores (see below)
make c8-rtl SEEDS=64 INSTR=1000 # random programs on the RTL against the reference model
```
`zexdoc.com` and `prelim.com` are not in this repo: `sw/exerciser/fetch.sh` downloads them, pinned by commit and sha256 (`sw/exerciser/README.md`). Both are GPL-2.0-or-later programs by Frank D. Cringle.

## Repo map
`docs/spec.md` the spec, `docs/blocks.md` the block split, `rtl/` Verilog, `tb/` and `tests/` the testbenches and tests (`tests/coverage.md` lists behaviour to test), `ref/` and `sw/cpm_ref.py` the reference model, `sw/demo/` the demo, `sw/exerciser/` the acceptance runner, `synth/` synthesis, `logs/` the evidence.

## The design
Five blocks plus a top, split by who builds what (`docs/blocks.md` §1):

| Block | What it does |
|---|---|
| `z80_timing` | T-state counter, the half-T phase, WAIT and BUSRQ sampling, bus strobes |
| `z80_decode` | combinational: opcode and prefix to a cycle plan; generated and checked by script against the spec's opcode list |
| `z80_control` | instruction register, prefix state, interrupt state (IFF1/2, IM, NMI latch, EI delay), HALT |
| `z80_alu` | 8-bit ALU, flags, DAA, rotates, BIT/SET/RES, the alternate AF |
| `z80_regs` | register file with the alternate bank (EXX), IX, IY, SP, PC, I, R, the 16-bit incrementer and the displacement adder |
| `z80` (top) | wiring and operand muxes |

The Z80 split differs from the 6502's because of the alternate register banks, 16-bit arithmetic and indexed addressing: `z80_regs` owns a real 16-bit address adder while `z80_alu` stays 8-bit, and 16-bit ADD/ADC/SBC run as two 8-bit ALU passes (`docs/blocks.md` §1).

### Decisions that shaped it
- **Decision 9 (b): 698 documented forms plus exactly 152 undocumented ones.** zexdoc executes undocumented opcodes in 9 of its 67 groups. Sai chose to specify those forms and run all 67 groups, rather than drop the test (spec §6.0a, chip-z80#14). The 152 are: U1, the IXH/IXL/IYH/IYL halves (92); U2, a DD/FD prefix that changes nothing before `LD r,r'` (50); U3, SLL (10). 850 forms in all. Every other undocumented opcode stays unspecified and untested (spec §1).
- **Decision 6 (ruled (a) by Sai, spec §3, PR #100): flag masks from Mostek.** zexdoc checks a few flags that the Zilog 1977 manual calls "X": S and Z after LDI/LDD, H after CPI/CPD, H after CCF. The Mostek MK78515 manual (1978) gives definite values for those, and they are what zexdoc expects (spec §6.2). The ruling is to use Mostek's values; the RTL follows it.
- **Our own definition of the X/Y flag bits (3 and 5).** They are 0 after any flag-writing instruction and compared as ordinary state (spec §1, §6.3). Real hardware copies result bits into them, so `zexall` would fail and `zexdoc` (which masks them) is the right acceptance test.
- **The half-T pin model (spec §4.0).** The manual puts MREQ, RD, WR and WAIT sampling on the falling clock edge, in the middle of a T state. So one model clock is one *half* T state and every pin is compared in every half. The 8080 compared once per T state; that would hide most of what makes Z80 bus timing different.
- **Decision 8 (ruled (a) by Sai, spec §3, PR #100): DAA outside the 13-row table, and H after DAA.** Neither Zilog manual defines these, and zexdoc's `daa` test checks them. The ruling takes the NMOS behaviour from Sean Young, *The Undocumented Z80 Documented* v0.91, §4.7 (read and quoted in spec §6.2), with zexdoc as the check. The reference-model runs below use `--daa nmos`.
- **Decision 7 (ruled (a) by Sai, spec §3, PR #100): instruction cycle types come from Mostek's MK3880 manual §12** (spec §6.1); where it gives no cycle breakdown (e.g. `LD (IX+d),n`, CPI/CPD), the spec fixes it as our own decision (A4).

## Results
Logs are in `logs/`. Each log starts with the commit it ran on.

| Check | Result | Log |
|-------|--------|-----|
| **Acceptance test 1: zexdoc** (Cringle's Z80 instruction exerciser), all 67 groups on the RTL, run sharded on GitHub Actions at commit 59dc956 | 67/67 OK, 0 timeouts, 0 bus conflicts, including the 9 decision-9 groups | `logs/acc-rtl/zexdoc-baseline-59dc956.log` |
| zexdoc, release run at commit 963359b | **[PENDING]** run 45556888466 started; no RTL changed since the baseline, so 67/67 is expected, but it is not counted until its log is committed | `logs/acc-rtl/zexdoc-*.log` (to come, #55) |
| `prelim` (Cringle's quick pre-check) on the RTL | "Preliminary tests complete", no timeout, no bus conflict | `logs/acc-rtl/prelim.log` |
| prelim and zexdoc on our Python reference model (`sw/cpm_ref.py`, Mostek flag policy, decision-9 groups not yet; #74) | prelim completes; per-group results are in the summary | `logs/acc-ref/prelim-mostek-nmos.log`, `logs/acc-ref/zexdoc-mostek-nmos-summary.log` |
| **Demo:** `demo.com`, our own CP/M program (LDIR, IX indexing, DJNZ) on the RTL, console output compared with the reference model | `RESULT PASS`, byte-identical | `logs/demo-rtl.log`, `logs/demo-ref.log` |
| **Bus-level tests C2 to C6:** every pin compared in every half T state for basic cycles, WAIT, interrupts (IFF1/2, EI delay, NMI, modes 0/1/2, HALT exit), bus request, reset | 74 cases pass on the RTL | `logs/z80-bus-c4-rtl.log` |
| The same 74 expected traces agree with the reference model | 0 disagreements | `logs/z80-bus-crosscheck.log` |
| The test harness itself: a replay DUT passes, a deliberately flipped pin fails | pass | `logs/z80-bus-harness-selftest.log` |
| **C8 random programs vs the reference model, DUT = RTL**, 8 seeds x 300 instructions | 8/8 seeds, 0 differences. The coverage check fails at this size (every form must be hit; it needs the 64-seed run), so the target reports `FAIL random` | `logs/random-c8-rtl.log` |
| C8 at full size (64 seeds x 1,000 instructions) | **[PENDING]** on the RTL. On the reference model alone (model against itself, tests the generator and the checker): 64 seeds pass, and every allowed form is executed at least once | `logs/random-c8-refvsref.log`, `logs/random-c8-coverage.log` |
| Reference model self-tests | 27 tests pass | `logs/ref-selftest.log` |
| Decoder table against the spec: 850 forms (698 documented + 152 decision 9), generated file matches the script's output | cycle plan vs spec §6.1: 0 mismatches over 850 forms; T states vs the reference model: 0 mismatches over the 698 documented forms (the model does not have the 152 yet) | `logs/z80_decode-check.log` |

### How long zexdoc takes
On our 2-CPU machine the RTL runs about 0.3 million half-clocks per second, so group 5 alone would be about 40 billion half-clocks. We sharded the run: each long group is its own job on a GitHub-hosted runner, and a merge step joins the logs. The first full run took 3 h 08 min wall, set by group 5; group 6 took 1 h 37 min (`logs/acc-rtl/zexdoc-sharded-runtimes.md`).

## Size and speed
Synthesis only so far: `synth/report.txt` (details in `synth/README.md`, logs in `synth/logs/`). **These numbers were made at RTL commit 8b11e74, before decision 9's decode, control and ALU changes (#51, #52, #53), so they are not the numbers for the chip whose zexdoc result is quoted above.** They will be regenerated on the same RTL as the layout run (#54). Yosys maps to the open sky130_fd_sc_hd cells at the typical corner; OpenSTA times the result with **ideal wires and clock**, so these are gate delays only, not a layout.

| Block | Cells | Flops | Area (µm²) | Worst path (ns) |
|---|---|---|---|---|
| `z80_alu` | 693 | 35 | 4,858 | 4.44 |
| `z80_regs` | 2,336 | 193 | 16,555 | 11.96 |
| `z80_timing` | 166 | 19 | 1,247 | 3.80 |
| `z80_control` (with decode) | 1,946 | 42 | 11,107 | 8.70 |
| **Full chip `z80`** | **5,375** | **289** | **34,486** | **14.68** |

The full chip has no latches and passes Yosys `check -assert`. The longest path is 14.68 ns, which is 14.68 ns of gate delay at an ideal clock with no clock tree and no wires; it is not a real top speed and no frequency is claimed.

**[PENDING, #54] sky130 place-and-route:** die size, routed wire length, router DRC count and a layout image will go here, with the picture `synth/sky130/layout.png`. Until then there are no layout numbers and none are claimed.

## What we learned
- **The 8080 and 6502 lessons paid off.** `docs/blocks.md` lists them up front (every mux select has a code table, separate write enables for A and F, a same-cycle 16-bit load path, a computed byte that is written to memory goes through TMP, never straight from the ALU result). The list is there so the same mistakes were not repeated; we have not counted how many were avoided.
- **The spec's half-T model made the bus tests honest.** Most Z80 timing is in the half-cycle edges, and per-T comparison could not have checked those edges.
- **zexdoc is a long test, so we made it parallel.** A single run would have been about 8.6 core-hours; sharding it across a hosted runner per long group brought the wall time to just over 3 hours (#78, #80).
- **Undocumented forms matter for acceptance.** zexdoc forced decision 9: a chip that follows only the manual cannot pass the standard Z80 exerciser.

## What went wrong along the way
This section is not complete until release; it lists what the issue history already shows.
- The spec had gaps found only when the expected bus traces were written: the BUSRQ release rule, reset boundary halves (#11), and two pin cases the random test could not decide, `halt_n` at HALT's own end and `d_oe` in the extra T state after a write (#18, #31).
- The 8-seed C8 run on the RTL reports `FAIL random` because coverage needs the full run. The target is designed that way (`C8_COVER`); a visitor running it at its default size will see the line.
- A C8 coverage hole was found by Beru late: the 28 half-register reads with IX/IY different from HL are not checked by counting alone (#86, open).

## Not done
- Layout (#54) and anything beyond it: timing closure, power, clock tree, signoff DRC and LVS.
- The release zexdoc run and the full-size C8 RTL run (see **[PENDING]** above).
- C7 (bus conflict positive case) tests are in progress (#85); the zexdoc, prelim and demo logs show `bus_conflict=0`.
- The 9 decision-9 groups on the reference model (#74).
- Undocumented opcodes outside the 152 are not specified and not tested. Block I/O flags that neither Zilog nor Mostek define are not compared.
- Spec v1 is signed off (PR #100): decisions 6, 7 and 8 and the also-open items A1–A6 are rulings in spec §3. The decode-layout log `logs/random-decode-xcheck.log` and the decision-6 forms in C8 are due a refresh (#101).
- The synthesis table predates decision 9's RTL changes (see Size and speed).

## Credits
`zexdoc` and `prelim` are by Frank D. Cringle (1994, GPL-2.0-or-later), fetched from github.com/agn453/ZEXALL and github.com/begoon/yaze at pinned commits; they are not in this repo. The spec follows the *Z80-CPU Technical Manual* (Zilog, 1977) and the *Z80 Assembly Language Programming Manual* (1978); flag details and cycle types come from Mostek's MK78515 (1978) and MK3880 (1977) manuals, as spec §10 lists page by page.
