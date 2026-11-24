# C8: random programs vs the reference model (`tests/random/`)

Beru, chip-z80#8. Spec: draft `docs/z80/spec.md` §7 C8, §8.4, with spec v1 candidate (chip-z80#10) readings where it
settles something. Nothing here reads RTL. C8 = random programs over the 698 documented forms, random
WAIT/INT/NMI/BUSRQ stimulus, every pin compared in every half T state.

## Run it
```
tests/random/run.sh                 # what `make test` runs: SEEDS=64 seeds x INSTR=1000 instructions, DUT=ref
SEEDS=8 INSTR=300 tests/random/run.sh        # quick
DUT=rtl RTL_TRACE_CMD='scripts/rtl_trace.sh' tests/random/run.sh     # the one-line switch, once RTL exists
```
Logs go to `$RUN_DIR` (default `logs/<timestamp>/`), one `random-*.log` per step. The committed run is
`logs/random-c8-refvsref.log` + `logs/random-c8-coverage.log`.

## Pieces
| File | Does |
|---|---|
| `gen.py` | seeded generator: image + stimulus + the model's expected pin trace (`--seed N --out base`) |
| `refrun.py` | the model as a DUT: replays image + stimulus only and writes a trace (ref-vs-ref) |
| `compare.py` | diff two traces: first difference with half, pin, both values, instruction in flight |
| `cover.py` | per-form executed counts (698 - excluded) and stimulus kinds hit |
| `xcheck_bus.py` | model vs Titus's directed bus vectors (two implementations of §4, same spec) |
| `seed.sh`, `run.sh` | glue, toolchain test convention (chip-6502#52) |
| `../../ref/pinsz80.py` | the pin-level model: M-cycle layout per §6.1, half-T rows per §4.1-4.7, stimulus rules |

## What ref-vs-ref proves, and what it doesn't
`gen.py` runs the model closed-loop while it builds the program. `refrun.py` then replays the final image and the
stimulus file alone, with no generator, and its trace must equal the generator's. That proves the *image and stimulus
files determine the trace*, which is exactly what the RTL run relies on. It does not test the model against the spec:
that is `ref/test_pinsz80.py` (rows typed from the spec tables) and `xcheck_bus.py` (Titus's independently built
expected vectors, 40 of 48 cases replayable, all agree; the other 8 reset mid-run, which C8 doesn't do).

## Trace format
The layout `z80_system` dumps with `+TRACE=<prefix>` (chip-z80#12), so a DUT trace goes straight into `compare.py`:
`half a d_out d_oe m1_n mreq_n iorq_n rd_n wr_n rfsh_n halt_n busak_n bus_oe | wait_n int_n nmi_n busrq_n reset_n d_in`.
Half 0 is the first rising edge with `reset_n` low; reset is released at half 8 and the first T1H is half 10
(`zbus.powerup()`, spec v1 §5 item 3a). In the expected trace `x` = not compared (floating pins, `a` in internal T
states, `d_out` while `d_oe` = 0). Per seed `gen.py` writes `sN.pins` (expected), `sN.stim` (inputs per half + `vec`),
`sN.hex` (image), `sN.idx` (instruction starts), `sN.cov.json`, and `sN.vec/` in the tb's own vector packing
(prog/stim/exp/mask/inp.hex, plus `vec.hex`) with `sN.case` = the `cases.txt` line.

## What the tb needs for C8 (asked of Titus, who owns `tb/`)
1. The environment now matches the stock tb: IN data = port[7:0] ^ A5H.
2. **INTA data**: the stock tb drives FFH (RST 38, mode 0). C8 needs a per-half `vec.hex` (8 bits per half) read as
   `d_in` while `m1_n = iorq_n = 0`, because the vector must suit the interrupt mode at that moment (mode 0: RST p,
   mode 2: even byte).
3. **MAXH**: C8 cases are 10-40k halves; the stock arrays are 8192.
4. A way to run `tests/random/build/c8/s*.vec` cases (a `cases.txt` of those lines).
Until then `DUT=rtl RTL_TRACE_CMD=...` can wrap any testbench that dumps the format above.

## Generator rules (so every case is determined)
- **Forms**: all 698 documented forms (§6.0) from `ref/refz80.census()`, minus `gen.EXCLUDED`, the one list that
  holds the forms the model raises `Unspecified` on in every state: LDI/LDD/LDIR/LDDR, CPI/CPD/CPIR/CPDR (decision 6),
  CCF (decision 6): 9 forms. When Sai settles decisions 6 and 8, delete rows there and switch the model's `Policy`.
  Every other `Unspecified` is state-dependent (DAA outside the 13-row table, consuming a don't-care flag) and is
  rejected by the trial run.
- **Trial run**: each new instruction runs on a copy of the CPU first. Kept only if the model doesn't raise, it
  writes only to >= 4000H, SP stays in 4010H..FFF0H, I in 3CH..3FH, and PC lands in code (100H..37FFH, or a RST stub).
  Bytes the run fetched or read are frozen, so the final image replays the same run. When control reaches frozen code
  in a state where it raises, the run ends (`stop=dead-end`, about 40% of seeds); that is counted, not hidden.
- **Layout**: `0000 JP 0100`, RST stubs at 08..38 (`body; EI; RETI`, also mode-0 and mode-1 vectors), NMI handler at
  0066 (`body; RETN`), preamble at 0100 (SP, I, R, IM, every register and flags written before use, §5 decision 1),
  random code from there, IM 2 handler stubs at 3800, vector tables at 3C00..3FFF, data and stack from 4000.
  Handler bodies are register-only instructions that can't raise, so they're safe in any state.
- **Stimulus** (`Stim` in `gen.py` proposes, `PinSim` enforces the §8.4 item 7 rules): WAIT per T state (changes at
  rising edges); INT, NMI, BUSRQ change only at a T1H (BUSRQ also at a Tx rising edge, to release); INT may be withdrawn
  before acknowledge; the INTA vector is RST p (p != 0) in mode 0, an even byte in mode 2. Seven profiles by seed
  (quiet, waits, int, nmi, busrq, all, heavy). INT/NMI/BUSRQ interplay follows spec v1 §8.4 item 4: BUSRQ sampled 0
  at an instruction end blocks both interrupts at that point.
- **Coverage** (`cover.py`, PASS needs every allowed form executed and every stimulus kind hit): rotating walk through
  all forms plus uniform random picks, so a few dozen seeds reach forms that need a rare state.

## Where the draft spec leaves a case undetermined
Filed as `Igris:` issues; until answered the generator avoids the case and the model's choice is marked `SPEC-GAP` in
`ref/pinsz80.py`: (3) INT/NMI visible at the end of HALT's own M1, where `halt_n` is not defined (the generator forces
INT/NMI high at HALT's T1H; a pending NMI inherited from a handler stops the run), (4) `d_oe` in the extra T states
after a write (§4.2 "drops at the next T1H" vs §6.1 lengthened-cycle rule 2 "d_oe = 0"; the model follows rule 2).
