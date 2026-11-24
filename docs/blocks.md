# Blocks: Zilog Z80 (Chip #4)

Owner: Igris (Architect) · Spec: `docs/spec.md` · Status: **v1 candidate** (chip-z80#6), signed off with the spec. Moved from `TuriChips/turichips` `docs/z80/blocks.md` (draft v0, turichips#37), with §2 and §3 written. None of §2–§3 depends on open decisions 6 or 8; `mc_type` (§2.1) encodes the cycle types of decision 7, recommendation (a).

Only the pins of `z80` (spec §2) and of `z80_system` are normative for tests. The internal ports below are the contract **between Zura (control) and Ada (datapath)**: tests don't bind to them, and neither designer changes one without a PR the other reviews. Ports between two of Zura's own blocks (`z80_timing` ↔ `z80_control` ↔ `z80_decode`) are written down here so the top can be wired, but Zura may change them alone.

**Top module: `z80`, in `rtl/top.v`**, as `i8080` and `m6502` were. The chip-z80 Makefile's `TOP ?= z80_top` is changed to `z80` by Tesla (the toolchain v0.9 doesn't read `TOP`, so nothing breaks meanwhile).

**Clocking.** One model clock is **one half T state** (spec §4.0). Everything is synchronous to the rising `clk`. `z80_timing` keeps the phase bit `ph` (0 = the H half, Φ high; 1 = the L half, Φ low). Edges the manual puts on Φ's falling edge (MREQ/RD fall mid-T1, WR mid-T2, read data in M2–M5, WAIT, HALT, BUSAK high) happen at the model edge that starts an L half. Rising-edge events happen at the edge that starts an H half. Pin outputs are registered per half, so every pin is stable for a whole model cycle, as compared (spec §4.0).

**The one timing rule for every code below.** A datapath operation (`*_op`, `*_we`, `f_load`, `af_swap`, a TMP or IR load) is asserted by control **for one model cycle (one half)**, and acts at the rising `clk` edge that **ends** that half. So "PC + 1 at the edge that starts T3H" means `pc_op` = 1 during the half before T3H (T2L, or the last TwL). Selects (`addr_sel`, `d_out_sel`, `alu_*_sel`, `rd_*_sel`, `pair_sel`, `bit_n`) are combinational and act in the half they're driven. Reads (`addr`, `rd_a`, `rd_b`, `a_out`, `f_out`, `result`, `bc_nz`, `b_nz`) are combinational from the current register values.

**Lessons applied up front** (8080: chip-8080#16, #20, #28, #37; 6502: chip-6502#9, #24, #31, #35, #39, #42):
- Every mux select has a code table here, not "control decides".
- Separate write enables for A (`a_we`) and for F (`f_we`, `f_load`).
- A load path for a 16-bit address whose high byte arrives in the **same** cycle as the jump: `pc_op` 3, PC ← {`d_in`, WZL} (JP nn, JP cc,nn, RET's SRH).
- Any opcode or field that control decodes from `ir` instead of the decode table is **listed** (§3, `z80_control`).
- Every latch whose input is muxed has its select in this contract: TMP's source is `tmp_src` (§2.6).
- The data-bus source reaches every register that is ever stored or pushed: A, F (`d_out_sel` 0, 1), B, C, D, E, H, L, I, R, IXH, IXL, IYH, IYL, SPH, SPL, PCH, PCL (`d_out_sel` 2 through `rd_b`), and TMP (`d_out_sel` 3: every computed or copied memory byte).
- A computed byte that is written to memory goes **through TMP**, never straight from `result`. The ALU's `result` depends on the flags (RL, RR, ADC, ...), and the flags change in the same half the operation is done, so a later write cycle would see a different `result`.

## 1. Block list

| Block | File | Owner | State it holds |
|-------|------|-------|----------------|
| `z80_timing` | rtl/control/z80_timing.v | Zura | The T-state counter, the half phase `ph`, Tw/Tw\* handling and the WAIT sample, the BUSRQ sample and the Tx (bus-request) state, the lengthened-cycle extra T states (spec §6.1). Generates the bus strobes of spec §4 from `mc_type`/`mc_len` |
| `z80_decode` | rtl/control/z80_decode.v | Zura | none (combinational from `prefix` and `ir`: the cycle plan row, ALU op, register selects; generated and checked by script against spec §6.0/§6.1, as the 6502's `gen_decode.py`) |
| `z80_control` | rtl/control/z80_control.v | Zura | IR, the prefix state, the cycle-plan step, TMP, IFF1, IFF2, IM, the NMI edge latch and pending bit, the EI-delay bit, the HALT state |
| `z80_alu` | rtl/datapath/z80_alu.v | Ada | A, F, A', F' and the bank bit of EX AF,AF'; the 16-bit-add latches `c16` and `z16`; 8-bit ALU, DAA, rotates and shifts, BIT/SET/RES |
| `z80_regs` | rtl/datapath/z80_regs.v | Ada | B C D E H L and their alternates (with the EXX bank bit), IX, IY, SP, PC, I, R, the address latch WZ; the 16-bit incrementer/decrementer, the displacement adder (pair + d, PC + e), the address mux |
| `z80` | rtl/top.v | Zura | none (wiring, the ALU operand muxes and the data-out mux, §2.4–§2.5) |
| `z80_mem` | rtl/datapath/z80_mem.v | Ada | A RAM of 2^`AW` bytes for tests (`$readmemh`). The system uses it twice: 64 KiB memory (`AW` = 16) and the 256-byte I/O space (`AW` = 8) |
| `z80_system` | rtl/control/z80_system.v | Zura | console and CP/M stub hooks, the data-bus source mux, WAIT/INT/NMI/BUSRQ/RESET stimulus pass-through, `bus_conflict` |

**Why the split differs from the 6502's:** the Z80 has an alternate register set (EX AF,AF' and EXX swap whole banks), 16-bit arithmetic, and indexed addressing with a signed displacement. So `z80_regs` owns a real 16-bit adder for addresses, while `z80_alu` stays 8-bit plus the flags. 16-bit ADD/ADC/SBC (spec §6.1, OCF IO(4) IO(3)) run as **two 8-bit ALU passes**, low byte first, with the carry and zero of the low byte kept in the ALU (`c16`, `z16`; §2.3).

## 2. Shared codes (control ↔ datapath)

### 2.1 Cycle types (`z80_control` → `z80_timing`)
`mc_type` (3 bits), the type of the current M cycle, from spec §6.1's cycle-type column (MK3880 §12, decision 7 (a)):

| code | type | spec | MK3880 labels it covers | pins |
|------|------|------|--------------------------|------|
| 0 | OCF: opcode fetch | §4.1 | OCF; also the halted M1 (§4.7) and NMI's dummy fetch (§8.2) | `m1_n`, MREQ/RD, refresh in T3–T4 |
| 1 | MRD: memory read | §4.2 | OD, ODL, ODH, MR, MRL, MRH, SRL, SRH; the DD CB op-byte read (OD(5), spec §6.1) | MREQ/RD |
| 2 | MWR: memory write | §4.2 | MW, MWL, MWH, SWL, SWH | MREQ/WR, `d_oe` |
| 3 | PRD: port read | §4.3 | PR | IORQ/RD, automatic Tw\* |
| 4 | PWR: port write | §4.3 | PW | IORQ/WR, `d_oe`, automatic Tw\* |
| 5 | IO: internal | §6.1 | IO | none; every strobe inactive, `a` not compared |
| 6 | INTA: interrupt acknowledge | §4.5, §8.2 | INTA | `m1_n` + IORQ, two Tw\*, refresh in T3–T4 |
| 7 | unused | | | control never drives it |

`mc_len` (3 bits), the cycle's length in T states **as spec §6.1 writes it**: the automatic Tw\* of PRD/PWR/INTA count, WAIT-inserted Tw don't. The **extra T states** are `mc_len` minus the base and follow the basic ones (spec §6.1, lengthened-cycle rule 1).

| `mc_type` | base | legal `mc_len` | extra T states |
|-----------|------|----------------|----------------|
| OCF | 4 | 4, 5, 6 | T5, T6 |
| MRD, MWR | 3 | 3, 4, 5 | T4, T5 |
| PRD, PWR | 4 | 4 | none |
| IO | — | 3, 4, 5 | all of them are internal |
| INTA | 6 | 6 (mode 0), 7 (modes 1, 2) | one extra T after T4, `t` = 7 (not T5 of the §4.5 table) |

`mc_type` and `mc_len` must be valid from the T1H of their M cycle to its last half; control changes them only at the edge where `mc_end` = 1 (§3, `z80_timing`).

### 2.2 Register codes (`z80_regs`)
**`r8` code** (4 bits), naming one byte inside `z80_regs`. Used by `rd_a_sel`, `rd_b_sel` and `wr_sel`. Codes 0–5 are the Z80's own `r` field (`ir[5:3]` or `ir[2:0]`), so control passes it through, except `r` = 6 ((HL), never a register) and `r` = 7 (A, which lives in `z80_alu`).

| code | byte | | code | byte |
|------|------|-|------|------|
| 0 | B | | 8 | IXH |
| 1 | C | | 9 | IXL |
| 2 | D | | 10 | IYH |
| 3 | E | | 11 | IYL |
| 4 | H | | 12 | SPH |
| 5 | L | | 13 | SPL |
| 6 | I | | 14 | PCH |
| 7 | R | | 15 | PCL |

B–L mean **the current bank** (EXX, `pair_op` 4). IXH/IXL/IYH/IYL are used internally (PUSH/POP IX, LD IX,(nn), ADD IX,pp) and, since decision 9 (b), named directly by spec §6.0a **U1**: under DD, an `r` field of 4 (H) becomes code **8 (IXH)** and 5 (L) becomes **9 (IXL)**; under FD, 4 → **10 (IYH)** and 5 → **11 (IYL)**. That applies to both fields of LD r,r' (DD 65 = LD IXH,IXL: source 9, destination 8), LD r,n, INC/DEC r and the ALU-A,r group, and only to the U1 opcodes listed there. Forms with (HL) keep the real H and L (DD 66 = LD H,(IX+d) writes code 4). U2 (DD/FD before LD r,r' with r, r' ∈ {B, C, D, E, A}) uses the same codes as the unprefixed form. WZ is not readable or writable through `r8`; it has `wz_op`.

**`pair_sel`** (3 bits), a 16-bit pair for `pair_op`, and as the source of `pc_op` 6 and `sp_op` 3:

| code | pair | | code | pair |
|------|------|-|------|------|
| 0 | BC | | 4 | IY |
| 1 | DE | | 5–7 | unused |
| 2 | HL | | | |
| 3 | IX | | | |

Control maps a DD or FD prefix to 3 or 4 where the instruction uses HL (spec §6.0's DD/FD forms). SP is never a `pair_sel`; it has `sp_op`.

**`pair_op`** (3 bits):

| code | operation | used by |
|------|-----------|---------|
| 0 | none | |
| 1 | pair ← pair + 1 | INC ss, INC IX/IY; LDI/LDIR/CPI/INI/OUTI's HL and DE |
| 2 | pair ← pair − 1 | DEC ss; LDD/CPD/IND/OUTD's HL and DE; BC − 1 of LDI…CPDR |
| 3 | DE ↔ HL (current bank; `pair_sel` ignored) | EX DE,HL |
| 4 | swap BC, DE, HL with BC', DE', HL' (`pair_sel` ignored) | EXX |
| 5 | pair ← WZ | the end of EX (SP),HL/IX/IY |
| 6 | WZ ← pair + sext(WZL), mod 2^16 (`pair_sel` 3 or 4) | the (IX+d)/(IY+d) address, spec §6.1a |
| 7 | unused | |

B − 1 for DJNZ and block I/O is **not** a `pair_op`: it goes through the ALU (op DEC, §2.3), which gives the flags of INI…OTDR. BC − 1 of the block moves and compares is `pair_op` 2 with `pair_sel` 0; it changes no flag, and `bc_nz` then feeds the ALU's P/V.

**`pc_op`** (3 bits):

| code | operation | used by |
|------|-----------|---------|
| 0 | none | |
| 1 | PC ← PC + 1 | every opcode and operand fetch, except the halted M1, NMI's dummy fetch, and INTA |
| 2 | PC ← PC − 2 | the IO(5) of a repeating block instruction (spec §6.1, §8.4 item 5) |
| 3 | PC ← {`d_in`, WZL} | JP nn and JP cc,nn taken (at ODH's sample), RET, RET cc, RETI, RETN (at SRH's sample) |
| 4 | PC ← WZ | CALL nn, CALL cc,nn taken (after SWL) |
| 5 | PC ← PC + sext(WZL), mod 2^16 | JR e, JR cc,e taken, DJNZ taken (in the IO(5)); spec §6.1a |
| 6 | PC ← pair (`pair_sel` 2, 3 or 4) | JP (HL), JP (IX), JP (IY) |
| 7 | PC ← {00H, `rst_vec`} | RST p (`rst_vec` = `ir` AND 38H), NMI (66H), INT mode 1 (38H), INT mode 0 with RST (the vector's `ir` AND 38H) |

INT mode 2 loads PC with the `r8` codes 14 and 15 (PCL then PCH through `wr_sel`, from the table read at WZ), since PC isn't the address in those cycles.

**`sp_op`** (2 bits): 0 none, 1 SP ← SP − 1, 2 SP ← SP + 1, 3 SP ← pair (`pair_sel` 2, 3 or 4: LD SP,HL/IX/IY). LD SP,nn and LD SP,(nn) write SPL and SPH with `wr_sel` 13, 12; INC SP and DEC SP are `sp_op` 2 and 1.

**`wz_op`** (3 bits), the address latch WZ:

| code | operation | used by |
|------|-----------|---------|
| 0 | none | |
| 1 | WZL ← `d_in` | the low operand byte (ODL), the displacement d and the offset e (OD), SRL of EX (SP),HL |
| 2 | WZH ← `d_in` | the high operand byte of CALL (ODH), LD rr,(nn), LD (nn),rr, LD A,(nn), LD (nn),A; SRH of EX (SP),HL |
| 3 | WZ ← {A, `d_in`} | IN A,(n) and OUT (n),A: the port address with A on A8–A15 (spec §6.1) |
| 4 | WZ ← {I, `d_in`} | INT mode 2: the table pointer at the vector's sample (spec §8.2) |
| 5 | WZ ← WZ + 1, mod 2^16 | the second byte of a 16-bit (nn) access, and of the mode 2 table (spec §6.1a) |
| 6, 7 | unused | |

**`addr_sel`** (3 bits), the source of `a` (via `z80_regs.addr`):

| code | `a` | used for |
|------|-----|----------|
| 0 | PC | OCF, OD/ODL/ODH, the DD CB op byte, the halted M1, NMI's dummy fetch, INTA's T1–T2 |
| 1 | SP | SRL/SRH/SWL/SWH |
| 2 | WZ | (nn), (IX+d)/(IY+d), the port of IN A,(n)/OUT (n),A, the mode 2 table |
| 3 | BC | LD A,(BC), LD (BC),A; the port of IN r,(C), OUT (C),r and the block I/O (B and C as they stand, so the order of B − 1 gives spec §6.1's "B before" for input and "B − 1" for output) |
| 4 | DE | LD A,(DE), LD (DE),A, the MW of LDI/LDD |
| 5 | HL | (HL) operands, the MR of the block instructions, MW of INI/IND |
| 6, 7 | unused | |

During refresh (`rfsh` = 1 from timing, the T3–T4 of OCF and INTA) `addr` = **{I, R}** whatever `addr_sel` is (spec §4.1, §4.5), with R as it stands, i.e. before this M1's increment (`r_inc` acts at the end of T4L).

### 2.3 ALU (`z80_alu`)
**`alu_op`** (6 bits). "SZ" = S and Z from `result`; "P" = even parity of `result`; "V" = two's-complement overflow; H is the carry/borrow out of bit 3. Every op that updates any flag also sets **F[5] = F[3] = 0** (spec §6.3 rule 1). Ops marked "none" never change F, whatever `f_we` is. Flags not listed keep their value. Where spec §6.2 says X, the RTL may produce any value (not compared), but it must be 0 or 1, never X/Z.

| `alu_op` | name | `result` | flags when `f_we` = 1 |
|---|---|---|---|
| 0 | PASS | `b` | none |
| 1 | ADD | `a_in` + `b` | SZ, H, V, C; N = 0 |
| 2 | ADC | `a_in` + `b` + C | as ADD |
| 3 | SUB | `a_in` − `b` | SZ, H, V, C (borrow); N = 1. With `alu_a_sel` 2 (00H) and `b` = A this is **NEG** |
| 4 | SBC | `a_in` − `b` − C | as SUB |
| 5 | AND | `a_in` & `b` | SZ, P; H = 1, N = 0, C = 0 |
| 6 | XOR | `a_in` ^ `b` | SZ, P; H = 0, N = 0, C = 0 |
| 7 | OR | `a_in` \| `b` | SZ, P; H = 0, N = 0, C = 0 |
| 8 | CP | `a_in` − `b` | as SUB. **A is never written**, even with `a_we` = 1 |
| 9 | INC | `b` + 1 | SZ, H, V (`b` = 7FH); N = 0; C kept |
| 10 | DEC | `b` − 1 | SZ, H, V (`b` = 80H); N = 1; C kept. Also B − 1 of INI…OTDR (spec §6.2: Z = B = 0, N = 1, S/H/P/V are X) |
| 11–18 | RLC, RRC, RL, RR, SLA, SRA, SLL, SRL | `b` rotated/shifted; **17 SLL** (spec §6.0a U3) = (`b` << 1) \| 1, i.e. SLA with bit 0 = 1 | SZ, P, C (the bit shifted out: `b`[7] for SLL); H = 0, N = 0 |
| 19–22 | RLCA, RRCA, RLA, RRA | `b` rotated (`b` = A) | C; H = 0, N = 0; S, Z, P/V kept |
| 23 | DAA | `b` (= A) adjusted per spec §6.2 (and decision 8) | SZ, P, C; H per decision 8; N kept |
| 24 | CPL | ~`b` | H = 1, N = 1 |
| 25 | SCF | `b` | C = 1, H = 0, N = 0 |
| 26 | CCF | `b` | C = ~C, H = old C (decision 6, Mostek), N = 0 |
| 27 | BIT | `b` | Z = ~`b`[`bit_n`], H = 1, N = 0; S, P/V X; C kept |
| 28 | SET | `b` \| (1 << `bit_n`) | none |
| 29 | RES | `b` & ~(1 << `bit_n`) | none |
| 30 | RLD | {`b`[3:0], A[3:0]} (the byte written back) | with `a_we`: A ← {A[7:4], `b`[7:4]}. SZ and P **of the new A**; H = 0, N = 0 |
| 31 | RRD | {A[3:0], `b`[7:4]} | with `a_we`: A ← {A[7:4], `b`[3:0]}. As RLD |
| 32 | IN | `b` | SZ, P of `b`; H = 0, N = 0; C kept (IN r,(C)) |
| 33 | LDAIR | `b` | SZ of `b`; P/V = `iff2`; H = 0, N = 0; C kept (LD A,I / LD A,R) |
| 34 | BLKLD | `b` | P/V = `bc_nz`; H = 0, N = 0; S, Z per decision 6 (Mostek: kept); C kept (LDI…LDDR, after BC − 1) |
| 35 | BLKCP | `a_in` − `b` | S, Z, H of `a_in` − `b` (H per decision 6, Mostek: the borrow from bit 4); P/V = `bc_nz`; N = 1; C kept. **A is never written** (CPI…CPDR, after BC − 1) |
| 36 | ADD16L | `a_in` + `b` | F unchanged. With `f_we` = 1: `c16` ← carry out, `z16` ← (`result` = 0) |
| 37 | ADC16L | `a_in` + `b` + C | as ADD16L |
| 38 | SBC16L | `a_in` − `b` − C | as ADD16L, `c16` ← borrow out |
| 39 | ADD16H | `a_in` + `b` + `c16` | C (carry out); H (carry from bit 3, spec §6.2 X); N = 0; S, Z, P/V kept |
| 40 | ADC16H | `a_in` + `b` + `c16` | C, H, V of this byte; S = `result`[7]; Z = (`result` = 0) & `z16`; N = 0 |
| 41 | SBC16H | `a_in` − `b` − `c16` | as ADC16H with borrows; N = 1 |
| 42–63 | unused | `b` | none |

Codes 1–8 are 1 + `ir[5:3]` of the `10 xxx rrr` / `11 xxx 110` ALU opcodes; 11–18 are 11 + `ir[5:3]` of the CB rotates; 19–26 are 19 + `ir[5:3]` of opcodes 07, 0F, …, 3F. So control may compute them instead of decoding them.

`a_we` writes A ← `result` (except CP and BLKCP, and RLD/RRD as written). `a_we` and `f_we` act at the same edge, and the flags are computed from the values **before** that edge.

**`alu_a_sel`** (2 bits), the first operand `a_in`, muxed in `z80`: 0 A (`a_out`), 1 `rd_a`, 2 00H (NEG), 3 unused.

**`alu_b_sel`** (3 bits), the second operand `b`, muxed in `z80`:

| code | `b` | used for |
|------|-----|----------|
| 0 | `d_in` | every byte loaded from the bus: immediates, (HL)/(nn)/(IX+d) reads, POP, IN |
| 1 | TMP | read-modify-write, CPI…CPDR, the byte of LDI/INI/OUTI where it's tested |
| 2 | `rd_b` | register operands: `alu r`, LD r,r', INC r, CB on r, 16-bit adds, LD A,I/R |
| 3 | A (`a_out`) | LD r,A, LD I,A, LD R,A, INC A, the accumulator rotates, CPL, DAA, NEG |
| 4–7 | unused | |

**Every 8-bit register in `z80_regs` is written only from `result`** (`wdata` = `result`, through `wr_sel`/`wr_we`), as the 6502's X and Y were. A plain load is op PASS with `f_we` = 0. POP AF and EX AF,AF' use `f_load` and `af_swap`.

### 2.4 Data out (`d_out_sel`, muxed in `z80`)

| code | `d_out` | used for |
|------|---------|----------|
| 0 | A | LD (BC)/(DE)/(nn),A, LD (HL),A, LD (IX+d),A, PUSH AF (SWH), OUT (n),A, OUT (C),A |
| 1 | F | PUSH AF (SWL) |
| 2 | `rd_b` | every other register stored or pushed: B…L, IXH…IYL, SPH/SPL, PCH/PCL (CALL, RST and the interrupt pushes), OUT (C),r |
| 3 | TMP | every computed or copied byte: INC/DEC (HL), the CB ops on memory, RLD/RRD, LD (IX+d),n, LDI/LDD's write, INI/IND's write, OUTI/OUTD's port write |
| 4–7 | unused | |

`d_out_sel`, `rd_b_sel` and TMP hold their values from T1H to T3L of a MWR or PWR cycle (spec §4.2–4.3: `d_oe` = 1 from T1L to T3L).

### 2.5 Flag-side controls
- `f_we` (1): F updates per `alu_op` (and `c16`/`z16` for ops 36–38).
- `f_load` (1): F ← `b`, all 8 bits (POP AF at SRL; spec §6.3 rule 3). Wins over `f_we`.
- `af_swap` (1): A, F ↔ A', F' (EX AF,AF'). Never with `a_we`, `f_we` or `f_load` in the same half.
- `bit_n` (3): the bit of BIT/SET/RES, = `ir[5:3]` (for DD CB / FD CB, of the op byte).
- `iff2` (1): IFF2 from control, for LDAIR. It's the value during the instruction (spec §8.1).

### 2.6 TMP (`z80_control`)
TMP is an 8-bit latch in control, output `tmp`. **`tmp_src`** (1 bit, internal to control but listed here per the 6502 #35 lesson): 0 = `d_in` (a read whose byte is written later or tested later: RMW reads, LDI/CPI/OUTI's MR, INI's PR, LD (IX+d),n's n), 1 = ALU `result` (the half in which the modify is done: TMP ← `result` at the same edge as `f_we`, so the write cycle sends the modified byte, §1 lessons).

### 2.7 Prefix state (`z80_control` → `z80_decode`)
`prefix` (3 bits): 0 none, 1 CB, 2 DD, 3 ED, 4 FD, 5 DD CB, 6 FD CB, 7 unused. A DD or FD followed by DD, ED or FD isn't a specified form (spec §6.0, §6.0a U2) and isn't tested.

## 3. Ports

Datapath blocks take `reset`, **active high**, synchronous: `reset` = NOT `reset_n`, made by the top. After `reset`: PC = 0000H, I = 00H, R = 00H (spec §5); every other register (A, F, A', F', B…L and alternates, IX, IY, SP, WZ, `c16`, `z16`) = 0 and both bank bits = 0. Spec §5 leaves them unspecified and tests never read them before writing; Ada clears them so a 4-state run never sees an X.

### `z80` (Zura): rtl/top.v
Exactly the pins of spec §2: `clk`; `reset_n`, `wait_n`, `int_n`, `nmi_n`, `busrq_n` in; `a`[15:0], `d_out`[7:0], `d_oe`, `bus_oe`, `m1_n`, `mreq_n`, `iorq_n`, `rd_n`, `wr_n`, `rfsh_n`, `halt_n`, `busak_n` out; `d_in`[7:0] in. No other port. It holds the `alu_a_sel`, `alu_b_sel` and `d_out_sel` muxes and `reset` = ~`reset_n`.

### `z80_timing` (Zura)
| Port | Dir | Width | Meaning |
|------|-----|-------|---------|
| `clk`, `reset` | in | 1, 1 | |
| `wait_n`, `busrq_n` | in | 1, 1 | Pins. WAIT sampled per spec §4.1–4.5; BUSRQ at the edge that starts the last T of every M cycle (spec §8.4 item 4) |
| `mc_type`, `mc_len` | in | 3, 3 | §2.1, from control |
| `t` | out | 3 | Current T state 1…7 (T1 = 1). Counts the automatic Tw\* as T states, as `mc_len` does: PRD/PWR are T1, T2, Tw\* = 3, T3 = 4; INTA is T1, T2, Tw\* = 3, 4, T3 = 5, T4 = 6, extra = 7. During WAIT-inserted Tw it holds the T state they follow (2 for OCF/MRD/MWR, 3 for PRD/PWR, 4 for INTA) |
| `tw` | out | 1 | The current T state is a WAIT-inserted Tw |
| `ph` | out | 1 | 0 = H half, 1 = L half |
| `tx` | out | 1 | In a bus-request Tx state: no M cycle runs, control asserts no operation |
| `d_strobe` | out | 1 | This half **ends at the edge where `d_in` is taken** (spec §4): OCF the half before T3H (T2L or the last TwL), MRD/PRD T3H, INTA the half before T3H. Control asserts every `d_in`-consuming operation only in this half |
| `samp_last` | out | 1 | This half ends at the rising edge that starts the **last T state** of the M cycle. INT, NMI and BUSRQ are sampled at that edge (spec §8.4 item 4; for a halted M1, T4) |
| `mc_end` | out | 1 | This is the last half of the M cycle. Control steps to the next M cycle at its edge and presents the next `mc_type`/`mc_len`, which timing uses from the next T1H (after any Tx) |
| `rfsh` | out | 1 | T3H–T4L of OCF and INTA: `z80_regs` puts {I, R} on `addr` |
| `r_inc` | out | 1 | T4L of every OCF and INTA (spec §6.3 rule 1: the increment acts at the end of T4) |
| `m1_n`, `mreq_n`, `iorq_n`, `rd_n`, `wr_n`, `rfsh_n` | out | 1 each | The pins, per the tables of spec §4.1–4.5 and the lengthened-cycle rule (§6.1). Registered |
| `d_oe`, `bus_oe`, `busak_n` | out | 1 each | Pins, spec §4.2–4.4 and §5. Registered |

Reset edges (spec §5 item 3a, chip-z80#11). `reset` is synchronous on `clk`, which ticks every half, so it can rise at a falling Φ edge (E0+1) and fall at one (E+1). Timing must still match the spec: the **first T1H after reset starts at a rising edge (E+2)**, so the half E+1 stays a reset half (`bus_oe` = 0, `m1_n` = 1). The outputs at E0+1 aren't compared.

### `z80_decode` (Zura)
In: `prefix` (3, §2.7), `ir` (8). Out: `specified` (1, the opcode is one of spec §6.0's **850** specified forms: the 698 documented plus decision 9's 152, §6.0a U1–U3; checked by script against `ref/refz80.py`'s census; renamed from `documented`, chip-z80#50) and the cycle-plan row and per-instruction fields, whose encoding is Zura's own (control and decode are both hers).

### `z80_control` (Zura)
| Port | Dir | Width | Meaning |
|------|-----|-------|---------|
| `clk`, `reset` | in | 1, 1 | |
| `d_in` | in | 8 | Data bus: IR, TMP, the mode 0 vector |
| `int_n`, `nmi_n`, `busrq_n` | in | 1 each | Pins. NMI's edge detector runs every model edge (spec §8.4 item 6); INT and BUSRQ are read at `samp_last` |
| timing's `t`, `tw`, `ph`, `tx`, `d_strobe`, `samp_last`, `mc_end` | in | 3, 1 × 6 | above |
| `f_out` | in | 8 | F, for the conditions |
| `result` | in | 8 | ALU `result`, for TMP (`tmp_src` 1) |
| `bc_nz`, `b_nz` | in | 1, 1 | From regs: the repeat and DJNZ conditions |
| `mc_type`, `mc_len` | out | 3, 3 | §2.1 |
| `addr_sel`, `rd_a_sel`, `rd_b_sel`, `wr_sel`, `wr_we` | out | 3, 4, 4, 4, 1 | §2.2 |
| `pair_sel`, `pair_op`, `pc_op`, `sp_op`, `wz_op` | out | 3, 3, 3, 2, 3 | §2.2 |
| `rst_vec` | out | 8 | §2.2, `pc_op` 7 |
| `alu_op`, `alu_a_sel`, `alu_b_sel`, `a_we`, `f_we`, `f_load`, `af_swap`, `bit_n`, `iff2` | out | 6, 2, 3, 1, 1, 1, 1, 3, 1 | §2.3, §2.5 |
| `d_out_sel` | out | 3 | §2.4 |
| `tmp` | out | 8 | TMP (§2.6) |
| `halt_n` | out | 1 | Pin, spec §4.7. Registered |

**Decoded from `ir` in `z80_control`, not from `z80_decode`** (the 6502 #39 lesson). Each is a bit field, so control reads it straight from `ir` (for DD CB d op / FD CB d op, from the op byte):
- **Conditions:** `ir[5:3]` for JP cc, CALL cc, RET cc (0 NZ, 1 Z, 2 NC, 3 C, 4 PO, 5 PE, 6 P, 7 M: Z is F[6], C F[0], P/V F[2], S F[7]); `ir[4:3]` for JR cc (0 NZ, 1 Z, 2 NC, 3 C).
- **`rst_vec`** = `ir` AND 38H for RST p and for mode 0's vector.
- **`bit_n`** = `ir[5:3]`; **`alu_op`** for the ALU, CB rotate and 07…3F groups as §2.3's arithmetic.
- **Register fields:** `ir[5:3]` and `ir[2:0]` → `r8` 0–5, with 6 meaning (HL) and 7 meaning A (`alu_*_sel`, `a_we`, `d_out_sel` 0). For spec §6.0a U1 opcodes under DD/FD, 4 and 5 map to 8/9 (DD) or 10/11 (FD) (§2.2 note).
- **Pair fields:** `ir[5:4]` (dd/ss/qq/pp/rr: 0 BC, 1 DE, 2 HL or IX/IY under a prefix, 3 SP or, for PUSH/POP qq, AF).
- **IM 0/1/2** (ED 46, 56, 5E): the mode from `ir[4:3]` (0 → 0, 2 → 1, 3 → 2).

Any other opcode that control treats specially from `ir` must be added to this list.

### `z80_alu` (Ada)
| Port | Dir | Width | Meaning |
|------|-----|-------|---------|
| `clk`, `reset` | in | 1, 1 | |
| `op` | in | 6 | `alu_op`, §2.3 |
| `a_in`, `b` | in | 8, 8 | Operands, muxed in the top (§2.3) |
| `a_we`, `f_we`, `f_load`, `af_swap` | in | 1 each | §2.3, §2.5 |
| `bit_n` | in | 3 | §2.5 |
| `iff2`, `bc_nz` | in | 1, 1 | For LDAIR, BLKLD, BLKCP |
| `a_out`, `f_out` | out | 8, 8 | A and F of the current bank |
| `result` | out | 8 | Combinational result of `op` |

### `z80_regs` (Ada)
| Port | Dir | Width | Meaning |
|------|-----|-------|---------|
| `clk`, `reset` | in | 1, 1 | |
| `d_in` | in | 8 | Data bus, for `wz_op` 1–4 and `pc_op` 3 |
| `wdata` | in | 8 | ALU `result`, the only source of an `r8` write |
| `wr_sel`, `wr_we` | in | 4, 1 | `r8` ← `wdata` |
| `rd_a_sel`, `rd_b_sel` | in | 4, 4 | `r8` codes |
| `pair_sel`, `pair_op`, `pc_op`, `sp_op`, `wz_op` | in | 3, 3, 3, 2, 3 | §2.2 |
| `rst_vec` | in | 8 | §2.2 |
| `a_val` | in | 8 | A (`z80_alu.a_out`), for `wz_op` 3 |
| `addr_sel` | in | 3 | §2.2 |
| `rfsh`, `r_inc` | in | 1, 1 | From timing (§2.2) |
| `rd_a`, `rd_b` | out | 8, 8 | The selected bytes |
| `addr` | out | 16 | The address pins `a`: {I, R} if `rfsh`, else by `addr_sel` |
| `bc_nz`, `b_nz` | out | 1, 1 | BC ≠ 0, B ≠ 0 (current bank) |
| `pc` | out | 16 | PC, for debug and tests' waveforms only |

Rules:
- `wr_we`, `pair_op`, `pc_op`, `sp_op` and `wz_op` are **independent fields and may act in the same half** (e.g. ODL: `wz_op` 1 and `pc_op` 1). Control never makes two of them write the same register in one half; if it did, the result is undefined.
- R: `r_inc` adds 1 to R[6:0] (mod 128), R[7] kept. A `wr_we` to R (code 7, LD R,A) in the same half wins.
- `pair_sel` is shared by `pair_op`, `pc_op` 6 and `sp_op` 3; control never needs two different pairs in one half.

### `z80_mem` (Ada)
Parameters `AW` (address width, default 16) and `INIT_FILE` (`$readmemh`, one byte per line, up to 2^`AW`; empty = no file). Memory is zeroed first.
| Port | Dir | Width | Meaning |
|------|-----|-------|---------|
| `clk` | in | 1 | |
| `addr` | in | `AW` | |
| `we` | in | 1 | Write `wdata` at `addr` on the rising edge |
| `wdata` | in | 8 | |
| `rdata` | out | 8 | Combinational: the byte at `addr`, always |

### `z80_system` (Zura)
Parameters `MEM_INIT`, `IO_INIT` (the two `z80_mem` files), `CPM` (1 = the spec §9 CP/M stub on).
| Port | Dir | Width | Meaning |
|------|-----|-------|---------|
| `clk` | in | 1 | |
| `reset_n`, `wait_n`, `int_n`, `nmi_n`, `busrq_n` | in | 1 each | Stimulus, passed to the CPU's pins |
| `int_vector` | in | 8 | The byte the system puts on the data bus in INTA (`m1_n` = 0 and `iorq_n` = 0): RST p in mode 0, ignored in mode 1, the vector in mode 2 (bit 0 = 0, spec §8.4 item 7) |
| every `z80` output pin | out | as spec §2 | Brought out for tests |
| `bus_conflict` | out | 1 | 1 if the CPU drives the data bus (`d_oe` = 1) in a half where the system also drives it (a read strobe or INTA active). Sticky until reset |
| `con_char`, `con_strobe` | out | 8, 1 | The CP/M stub's BDOS output, as chip-8080's: on an OCF from 0005H it performs function 2 (char in E) and 9 (string at DE, `$`-terminated), then returns |
| `done` | out | 1 | An OCF from 0000H after the first instruction: the program ended |

`d_in` of the CPU, muxed here: the memory's `rdata` while `mreq_n` = 0 and `rd_n` = 0; the I/O space's `rdata` at `a[7:0]` while `iorq_n` = 0 and `rd_n` = 0 (`m1_n` = 1); `int_vector` while `m1_n` = 0 and `iorq_n` = 0; else FFH. Writes: memory at every edge that ends a half with `mreq_n` = 0 and `wr_n` = 0, I/O the same with `iorq_n` (`a[7:0]` only). `d_out` and `a` are stable for the whole strobe (spec §4.2–4.3), so writing the same byte two or more times is harmless and needs no T-state knowledge.

## 4. Who does what first (when the spec is signed off)
1. **Ada:** `z80_alu` and `z80_regs` against §2–§3, then `z80_mem`.
2. **Zura:** `z80_timing`, then `z80_decode`/`z80_control` and `z80`, then `z80_system`.
3. **Titus:** C1–C7 on the pins, with `tests/coverage.md` (chip-z80#7 has started on C2, C3, C5, C6).
4. **Beru:** the pin-level reference model and C8 (chip-z80#8).
5. **Leo:** synthesis and sky130 layout.
6. **Homer:** zexdoc and prelim (chip-z80#5), the demo, the write-up.
7. **Tesla:** `TOP ?= z80` in the Makefile.

These become issues titled `<Name>: <task>` once Sai signs off the spec PR.
