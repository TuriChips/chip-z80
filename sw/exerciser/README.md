# Z80 acceptance programs: `prelim` and `zexdoc`

Both are Frank D. Cringle's programs from yaze (1994), **GPL-2.0-or-later**. We never commit them (rule 9):
`sw/exerciser/fetch.sh` downloads them into `build/third_party/` at test time, pinned by commit **and** sha256.

```
sw/exerciser/fetch.sh            # zexdoc.com + prelim.com
sw/exerciser/fetch.sh zexdoc-src # the original sources, for audit (zexdoc-src, prelim-src)
python3 -I sw/cpm_ref.py build/third_party/prelim.com --x6 mostek --daa nmos
```

## What is pinned (spec §9 item 1)

| File | Source, pinned commit | Bytes | sha256 |
|---|---|---|---|
| `zexdoc.com` (prebuilt) | agn453/ZEXALL @ `8f71d418bae69a476a5a0e5c6e122c8801b8d9f4` | 8,704 | `34923a7ed82285d3038b2d54bd64899e12173eebb61f9d07b4fc72e78af2ae8f` |
| `zexdoc.com` (same file, second source) | begoon/yaze @ `993d8647eabf95c61e49b134198a240ab577358b`, `test/zexdoc.com` | 8,704 | same hash |
| `zexdoc.z80` (original source) | begoon/z80exer @ `8634cccdd362e030efebcdeec1aeb8b4f2ce9179`, `yaze/zexdoc.z80` | 40,283 | `f82ccdea9ca0076aff11eac6d021276e2290344cd0e50e1353d5d1e46a981ef3` |
| `prelim.com` (prebuilt) | begoon/yaze @ `993d8647…`, `test/prelim.com` | 1,280 | `3b3578f19030a4df7e25ce852f763af26053b12582a576c4dffb014aa7c590d1` |
| `prelim.z80` (original source) | begoon/z80exer @ `8634cccd…`, `yaze/prelim.z80` (byte-identical to begoon/yaze `test/prelim.z80`) | 5,384 | `afefdd15c42ea8d0c123ad099108962ca5ad26b3ffd043d2ba578c2b01cab1fd` |

Neither agn453/ZEXALL nor begoon/z80exer ships a `prelim.com`; only begoon/yaze does.

**Licence of `prelim.z80`** (§9 [check], now checked): header reads "Copyright (C) 1994 Frank D. Cringle", GNU General
Public License version 2 or (at your option) any later version. Same as `zexdoc.z80`. So: GPL, fine to fetch and
run, not fine to copy into this repo. `fetch.sh` only downloads.

## Proposal: pin the prebuilt `.com` files

I propose pinning **`zexdoc.com` and `prelim.com`, the prebuilt binaries**, and recording the source hashes above for audit.

- **One program, two sources.** zexdoc.com from agn453/ZEXALL and from begoon/yaze are byte-identical (same sha256).
  That is the binary every emulator's published CRC results were produced with.
- **Our own assembly adds a tool to trust.** The sources are `aseg` + `tstr` macros for yaze's assembler (or zmac).
  Assembling them means pinning an assembler as well, and a different assembler version could give a different binary.
  I have no assembler in this environment, so **I have no "own assembly" hash to record**. I did not invent one.
  If Sai wants the source route, someone must pin zmac, assemble, and compare against the hash above;
  a match would close the question.
- **Not verified:** that `prelim.com` was assembled from the `prelim.z80` above. It is begoon/yaze's own build.
  It runs to its success message on the reference model (see below), which is a behavioural check only.

## First run on the reference model (`ref/refz80.py` @ `c7819e0`)

Runner: `sw/cpm_ref.py` (CP/M stub: load at 0100H, BDOS at FE00H so 0006H/0007H = FE00H, C=2 and C=9, stop on `JP 0000H`).
Logs: `logs/acc-ref/`. Speed is about 500,000 to 800,000 instructions/s; the longest groups need 10^9.

**`prelim`: passes** on the model, prints "Preliminary tests complete" after 898 instructions, under both policies:
`logs/acc-ref/prelim-mostek-nmos.log`, `logs/acc-ref/prelim-raise.log`.

**zexdoc, default `raise` policy: cannot get past its own setup code, with any group.** All 67 groups stop at the first
`LDI` in zexdoc's setup (decision 6, S/Z after LDI) once `--lenient-push` is on: `logs/acc-ref/zexdoc-lenient-raise.log`.
Without `--lenient-push` they stop even earlier, at `PUSH AF` after `ADD HL,DE` (H unspecified):
`logs/acc-ref/zexdoc-strict-mostek-nmos.log`.

**zexdoc, `Policy(x6='mostek', daa='nmos')` with `--lenient-push`:** per-group table in
`logs/acc-ref/zexdoc-mostek-nmos-summary.log` (merged from the part and long logs next to it; the 90 s pass timed out
on eight groups, which were rerun with a 1500 s limit).

| Result | Groups | Count |
|---|---|---|
| OK (CRC matches) | all others and the eight decision-9 groups 28-31, 48, 50, 59, 60 (`zexdoc-lenient-mostek-nmos.decision9.log`), including `ldd<r>` (1)(2), `ldi<r>` (1)(2), `cpd<r>`, `cpi<r>`, `<daa,cpl,scf,ccf>`, `add hl/ix/iy`, `adc/sbc hl` | 65 |
| ERROR (CRC mismatch) | none | 0 |
| not finished (no error): 5 in 884M instructions, 6 in 182M (slowed by a shared CPU) | 5 `aluop a,<b,c,d,e,h,l,(hl),a>`, 6 `aluop a,<ixh,ixl,iyh,iyl>` | 2 |

So **no zexdoc ERROR under mostek/nmos**. That is as far as 8-bit-ALU groups 5 and 6 allow: both ran past the 1500 s limit without an error. The eight other decision-9 groups run and pass on the ref (chip-z80#74).

**Which groups depend on decisions 6 and 8** (measured, not only read off the spec):
- Decision 8 (DAA): only group 12 `<daa,cpl,scf,ccf>`. With `daa='raise'` it stops at `A=8E C=1 H=0 N=0`
  (`zexdoc-lenient-mostek-daaraise-group12.log`). With `daa='nmos'` it is OK (136M instructions).
- Decision 6 (X flags): every group, because zexdoc's own setup uses `LDI`. The groups that *check* the flags:
  `ldd<r>` (1)(2), `ldi<r>` (1)(2) (S/Z), `cpd<r>`, `cpi<r>` (H), group 12 (H after CCF). With `x6='taint'` the four
  `ld?<r>` groups end in ERROR at once (`zexdoc-lenient-taint-nmos-ldcp.log`: ldd(1) found 0eb29fca, expected 94f42769;
  ldi(1) found baa208b1, expected 9abdf6b5); with `x6='mostek'` all of them are OK. That is the evidence for option (a).
- Not a decision-6/8 matter, but new: **nine groups execute undocumented opcodes** (list above). The spec says
  undocumented forms are "not specified, not tested" (§1, §6.0), so zexdoc as a whole cannot be the acceptance test
  unless those groups are excluded or the forms specified. Filed as a finding.

Two workarounds live in `sw/cpm_ref.py`, in subclasses, because `ref/` is Beru's:
- `Fast`: skips the `last` trace in `step()`. `step()` builds it with `range((pc - start) & 0xFFFF)`, which is thousands
  of bytes after every taken jump: about 800 instructions/s, a hundredth of the speed without it.
- `LenientPush` (`--lenient-push`): `PUSH AF` of an X flag does not raise. zexdoc's own setup does `ADD HL,DE` then
  pushes AF, so without this it cannot start under *any* policy. Safe for zexdoc because its flag masks hide X flags.

## Acceptance on the RTL (spec §9 item 1): `run_rtl.py`

```
python3 -I sw/exerciser/run_rtl.py prelim                      # seconds -> logs/acc-rtl/prelim.log
python3 -I sw/exerciser/run_rtl.py zexdoc [--groups N,N] [--jobs J]   # -> logs/acc-rtl/zexdoc.log (one line per group)
```
It builds `z80_system` (CPM=1) with Verilator and the bench `z80_acc_tb.sv`, then runs `prelim.com` and `zexdoc.com`
fetched by `fetch.sh` (sha256 recorded in each log header). zexdoc is run **one group per simulation** (the test table is
patched to hold that group), so groups run in parallel and one failing group cannot hide another.
The run exits 0 only if every group prints OK, the CP/M stub reaches warm boot (`done=1`) and `bus_conflict` stays 0.

**Cost.** The RTL simulates about 1.1 million half-clocks per second per core (about 19 half-clocks per instruction,
measured: `logs/acc-rtl/prelim.log` 17,484 half-clocks for 898 instructions). The reference model's table
(`logs/acc-ref/zexdoc-mostek-nmos-summary.log`) puts the 67 groups at several billion instructions, so the full zexdoc is
**tens of core-hours**, and one group (5, `aluop a,<b,c,d,e,h,l,(hl),a>`) is over 10^9 instructions on its own.
That is why the full run is a nightly/manual job (issue #58 asks Tesla for `make acceptance`), not PR CI.

**Logs.**
- `logs/acc-rtl/prelim.log`: complete run.
- `logs/acc-rtl/zexdoc-partial.log`: the short groups only, run to show the runner works end to end. **Not the release evidence.**
- `logs/acc-rtl/zexdoc.log` (all 67 groups; the final all-OK run is the release evidence): not committed yet, see issue #55.

Groups 6, 28-31, 48, 50, 59, 60 need decision 9's U1-U3 forms (chip-z80 #51, #52, #53) and are expected to fail until
those land. They are run and logged, never skipped.
