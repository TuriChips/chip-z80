# Z80 demo: `demo.com`

A small original CP/M program (our own code, no third-party files) that prints through the CP/M stub console
(BDOS 2 and 9 at 0005H, spec §7 `z80_system`) and uses things the Z80 added over the 8080:

| Step | Z80 feature | Output |
|---|---|---|
| copy a string, print the copy | `LDIR` block move | `LDIR copied this string.` |
| sum a table with `ld a,(ix+0)` / `add a,(ix+d)`, store with `ld (ix+8),a` | IX indexed addressing | `IX sum of 10,20..80 = 68` (360 mod 256 = 0x68) |
| print digits 0 to 9 | `DJNZ` loop | `DJNZ count: 0123456789` |

(IM 2 interrupts are not used: the CPM=1 acceptance bench ties `int_n` high.)

## Assembler

No Z80 assembler is installed in the lab, so `build_demo.py` is a tiny two-pass assembler-in-Python: each
instruction is emitted from the opcode table by hand. Run `sw/demo/build_demo.py` to regenerate `demo.com` (293 bytes)
and the listing `demo.lst` (address, bytes, source). Both are committed.

## Run

```
sw/demo/run_demo.py        # builds the bench if needed, runs RTL and ref model, compares
```
It reuses `sw/exerciser/run_rtl.py` (same `z80_system` CPM=1 bench, nothing forked) and writes
`logs/demo-rtl.log` (rtl commit in the header) and `logs/demo-ref.log` (`sw/cpm_ref.py --x6 mostek --daa nmos`,
same policy as prelim). Exit 0 only if the RTL finished with no bus conflict and the console output is byte-identical.
Use `heavy` on the shared machine.
