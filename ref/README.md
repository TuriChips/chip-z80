# Z80 reference model (`ref/`)

Instruction-level model of the documented Z80, by Beru (chip-z80#2). Written from the **draft** spec
`TuriChips/turichips` `docs/z80/spec.md` at commit **b871a30** (`igris/z80-spec-draft`), never from RTL.
Nothing here is normative until Sai signs the spec off; if the spec changes, the sections named on
chip-z80#2 get re-checked.

- `refz80.py`: the model. `Z80.step()` runs one instruction, one interrupt sequence or one halted M1 and
  returns its T states (§6.1, §8.2). A block repeat is one step per iteration (§8.4 item 5).
- `test_refz80.py`: self-tests (`python3 ref/test_refz80.py`). Expected values come from the spec text and
  independent arithmetic (Python ints, BCD maths), not from the model. Log: `logs/ref-selftest.log`.

## What it covers
698 documented forms (§6.0), checked by `census()`: main 252, CB 248, DD 70, ED 58, FD 70. Every other
encoding (SLL, IXH/IXL, DD CB register copies, ED 70, DD-prefixed non-IX opcodes, ...) raises `Undocumented`.
Registers, alternate set, IX/IY, I, R (§6.3: +1 per M1, prefixes count, DD CB op byte doesn't, halted M1s and
INTA/NMI count), IFF1/IFF2, IM 0/1/2 (mode 0 only RST, mode 2 vector bit 0 must be 0), EI delay, NMI/INT per
§8.4, HALT (PC stays at HALT+1), flags per §6.2 with F5/F3 as real state (§6.3 rule 1: any Table 6.0-1 row
clears them; POP AF and EX AF,AF' move all 8 bits). I/O port high byte per §6.1 (A for IN/OUT (n), B for the
(C) forms, B before the decrement for INI/IND, B-1 for OUTI/OUTD).

Not in the model: per-M-cycle bus types and pin timing (open decision 7), WAIT, BUSRQ, RESET timing. Only
T-state totals per instruction. C8's harness (separate issue) and a bus-cycle view come after sign-off.

## Open decisions: switches
`Policy(x6=..., daa=...)`, default `raise`.

| Switch | Decision | `raise` (default) | `taint` | implemented choice |
|---|---|---|---|---|
| `x6` | 6: S/Z after LDI/LDD(R), H after CPI/CPD(R), H after CCF | `Unspecified` at the instruction | flag marked don't-care in `cpu.fx`; raises only when consumed | `mostek`: MK78515 values (§6.2) |
| `daa` | 8: DAA outside the 13-row table, and H | outside the table: `Unspecified`. H: see below | as `raise`, but outside-table gives the NMOS value, all marked | `nmos`: the usual NMOS rule (option (a); not chosen yet) |

**H after DAA is always marked don't-care (`cpu.fx`), not raised**, except under `nmos`. Raising on it would
make DAA unusable until Sai rules, and no row of the table defines H. It raises when something consumes it
(a conditional, PUSH AF, ADC/SBC, a second DAA, ...). Say so if you want it eager.

**Don't-care flags.** `cpu.fx` is a mask on F. The flags Zilog marks X that no decision covers (H after
ADD/ADC/SBC HL and ADD IX, S and P/V after BIT, S/H/P/V after block I/O) are always tainted. Consuming a
tainted flag (conditional jump, carry-in, DAA, PUSH AF) raises `Unspecified`. The harness should compare
`F & ~fx` and avoid PUSH AF until the taint is gone. A flag-writing instruction that defines the flag clears it.

## Spec points to settle (questions for Igris, not guessed)
1. **EI delay wording.** §8.1: INT is accepted only after the instruction following EI. §8.4 item 5 also says
   "not accepted ... at the end of the instruction after it", which would be one instruction later.
   The model follows §8.1 (EI; X; INT taken at the end of X; EI;EI restarts the delay).
2. **Repeating block instructions, per iteration.** Table 6.0-1 lists LDIR/LDDR P/V = 0 and
   INIR/OTIR Z = 1, which only holds on the last iteration. The model uses the single-step rule
   (P/V = BC != 0, Z = B == 0), so an interrupt between iterations sees the same flags as LDI/INI.
3. **§1 vs §6.3.** §1 says F5/F3 are not compared; §6.3 and issue #2 define them as ordinary state. Model: §6.3.
4. LD A,I/R with an INT arriving during the instruction: P/V = IFF2 as before the interrupt (§8.1), modelled.
