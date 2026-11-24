# Coverage: spec behaviour -> test (Zilog Z80), bus-cycle part: C2 (basic cycles), C3, C4 (interrupts), C5, C6

Spec: draft `docs/z80/spec.md` (TuriChips/turichips `main`, 696e137); not normative until Sai signs off. Section numbers below are that file's.
Scope of chip-z80#7: §2 pins, §4 timing, §5 reset; chip-z80#64 adds C4, interrupts (§4.5-§4.7, §8). Not here: C1/C2 per opcode (decision 7), C7, C8 (Beru), acceptance.

**Status words.** *written*: the case exists, its expected trace is generated from the spec table named, and it agrees with `ref/refz80.py`
(`logs/z80-bus-crosscheck.log`, 74 cases, 0 disagreements). *run*: it has passed on RTL: **all 74 cases (C2, C3, C5, C6 and the 26 C4 cases) pass on the RTL**,
`logs/z80-bus-c4-rtl.log` (verilator, full-pin compare every half, no RTL failures, so no issue for Zura). The harness itself passed its self-test with a replay DUT
(`logs/z80-bus-harness-selftest.log`: 48 cases PASS, and a deliberately flipped pin FAILs; the 74 cases also PASS on the replay DUT, `logs/z80-bus-c4-mock.log`).

## How the tests work
- `tests/z80_bus/zbus.py`: expected pin traces, one row per half T state, written from the §4 tables. It reads no RTL. `tests/z80_bus/cases.py`
  holds the cases (program + input stimulus), writes `tests/z80_bus/vectors/<id>/` and cross-checks each program on the ref model.
  Regenerate with `python3 tests/z80_bus/cases.py`.
- `tb/z80_bus/` (`files.f`, `tb.sv`, `z80_system.sv`): the `z80_system` harness of §7. Loads `prog.hex`, replays the stimulus, records every pin
  every half (`+TRACE=<prefix>` writes the per-half trace), and compares to the expected vector under a mask (a masked bit = floating or
  don't-care in the spec). An X/Z on a compared pin fails. It also checks its own input stimulus against the plan (`inp.hex`).
- Programs use only NOP, HALT, EI, IM, LD (all forms of §6.1's load groups used), IN/OUT, LD I,A / R,A / A,I / A,R: opcodes whose cycle types §6.1 fixes.
- IN data = low port byte XOR A5H; INTA data = FFH (RST 38H). Both are harness conventions, mirrored in `zbus.py`.
- Instruction results are made visible on the pins: A, B, HL, R, I are shown with OUT (n),A / OUT (C),r (A15:8 carries the register, §6.1) or memory writes.

## §2 pins
| Behaviour | Test |
|---|---|
| `a` valid in every M cycle (PC for fetch, address for memory, port for I/O, {I,R} in refresh) | C2-01..C2-08 |
| `d_out`/`d_oe` on writes | C2-06, C2-07 (OUT), C3-04..C3-09 |
| `d_in` captured (opcode, memory read, I/O read, INTA vector) | C2-02/05/07 (results shown through OUT), C5-17/18 |
| `m1_n` asserted for every opcode byte incl. the ED prefix | C2-03, C2-04, C3-01..03 |
| `mreq_n`, `rd_n`, `wr_n`, `iorq_n`, `rfsh_n`, `halt_n`, `busak_n`, `bus_oe` per half | every case (full-pin compare every half) |
| `wait_n` | C3-01..C3-13 |
| `busrq_n` / `busak_n` | C5-01..C5-18 |
| `reset_n` | C6-01..C6-09 |
| `int_n` | C4-01..C4-15, C4-17, C4-20..C4-24, C4-26; also C5-17, C5-18, C6-09, C3-12/13 |
| `nmi_n` | C4-04..C4-07, C4-16..C4-20, C4-23, C4-25 (held inactive in all other cases) |
| `clk` | the harness drives it, 2 edges per T (§4.0) |

## §4 timing
| Spec behaviour | Test | Status |
|---|---|---|
| §4.0 one model clock = half T; every pin compared every half; inactive defaults; `a` holds / not compared per table | all | written |
| §4.1 M1 rows T1H..T4L (MREQ/RD fall at T1L, rise at T3H; RFSH T3H..T4L; MREQ refresh T3L..T4H) | C2-01, C2-02, C2-03, C2-08 | written |
| §4.1 refresh address {I,R}, R as at the start of the M1 | C2-01 (R = 0..), C2-03 (I = 5A), C2-04 | written |
| §4.1 decision: A7 = R bit 7; R6:0 wraps mod 128 | C2-04 | written |
| §4.1 prefix: ED and its opcode each an M1 and each +1 on R | C2-03, C2-04 (LD I,A, LD R,A, LD A,R, LD A,I) | written |
| §4.2 read rows (data taken at T3L) | C2-05 (via OUT of the loaded value) | written |
| §4.2 write rows (WR falls T2L, rises T3L, d_oe from T1L, d_oe low at next T1H) | C2-06, C2-07 | written |
| §4.2 `m1_n`=1, `rfsh_n`=1 throughout | C2-05, C2-06 | written |
| §4.3 I/O rows (IORQ/RD/WR fall at T2H, automatic Tw*, d_oe from T1L for OUT, d_oe 0 for IN) | C2-07 | written |
| §4.3 / §6.1 A15:8 = A for IN A,(n)/OUT (n),A and = B for (C) forms | C2-07 (A=12, B=34) | written |
| §4.0/§4.1 WAIT in M1: sampled at T2L and each TwL; Tw repeats the T2L row (1, 2, 3 waits) | C3-01, C3-02, C3-03 (NOP, LD B,(HL), ED prefix M1s) | written |
| §4.2 WAIT in memory read/write (Tw between T2 and T3; WR low through Tw) | C3-04, C3-05, C3-06 | written |
| §4.3 WAIT in I/O: sampled at Tw*L, extra Tw on top of Tw* | C3-07, C3-08, C3-09 | written |
| §4.0 WAIT is not sampled at T1, T3, T4 (and not at T2 for I/O) | C3-10 | written |
| waits in several cycles of one instruction | C3-11 | written |
| §4.5 WAIT in INTA, after the two Tw* (spec §7 C3) | C3-12, C3-13 | written |
| §4.4 BUSRQ sampled at the edge starting the last T; floats from the next rising edge; BUSAK low with it; `m1_n`, `halt_n` not floated; Tx count; BUSAK high at the falling edge after the release sample; buses driven from the next rising edge | C5-01..C5-14 (M1, memory read/write, I/O read/write, between M cycles of LD A,(nn); 2 and 3 Tx) | written |
| §4.4 sampling after the wait states | C5-15 | written |
| §4.4 consecutive requests | C5-16 | written |
| §4.4 / §4.5 no INT accepted during / with BUSRQ low at the sample; taken at the end of the next instruction | C5-17 (and C5-18, the positive case without BUSRQ) | written |
| §4.5 INTA rows (T1 T2 Tw* Tw* T3 T4; IORQ falls at Tw*1L; no MREQ/RD before T3; refresh {I,R} in T3-T4), mode 0 RST 38H = 12 T, R counts the INTA M1 | C5-18, C6-09 | written |
| §4.6 NMI response: M1-like cycle with the data byte ignored, PC not advanced, two stack writes, 0066H | C4-04..C4-07, C4-16..C4-20, C4-23, C4-25 | written, run |
| §4.7 HALT: halt_n falls at T4L of HALT's M1; halted M1s are §4.1 rows at HALT+1, data ignored, R counts, halt_n low throughout | C2-08 | written |
| §4.7 HALT exit by INT/NMI (halt_n rises at T4L of the accepting halted M1; pushed PC = HALT + 1) | C4-22, C4-23 | written, run |
| §4.7 interrupt accepted at the end of HALT's own M1: halt_n stays 1, no halted M1 (chip-z80#24, merged) | C4-24 (INT), C4-25 (pending NMI) | written, run |
| §4.7 BUSRQ low at HALT's own T4 sample: halt_n falls, bus request runs, interrupt taken at the end of the next (halted) M1 | C4-26 | written, run |
| lengthened cycles (§6.1 rule: extra T after T4, `a` not compared, no strobes, no WAIT sampling) | C2-03 (LD I,A), C2-04 (LD R,A, LD A,R) use OCF(5) only | written |
| lengthened cycles, other kinds (OCF(6), IO(n), MR(4/5)) | **out of scope**: per-opcode, decision 7 | - |

## §5 reset
| Spec behaviour | Test | Status |
|---|---|---|
| §5 item 4: reset held ≥ 3 T (6 halves, the minimum) and a longer reset | C6-01 (6 halves), C6-02 (22) | written |
| §5 item 3: first M1 at the first rising edge at which `reset_n` is sampled 1, address 0000H | C6-01..C6-09 | written |
| §5 item 2: during reset `bus_oe`=0, `d_oe`=0, `m1_n`=`halt_n`=`busak_n`=1 from the second reset T state | C6-01..C6-09 | written |
| §5: reset aborts the current cycle at any phase of an M1 (T1, T2, T3, T4) | C6-03..C6-06 | written |
| §5 / §6.3 HALT item 4: reset ends a halt, `halt_n` returns to 1 | C6-07 | written |
| §5: I = 00H, R = 00H (the first refresh address is {00,00} although I = 5A and R ≠ 0 before) | C6-03..C6-09 | written |
| §5 item 1: A, B, C, H, L, SP not reset ("no exemption window"): OUT (n),A shows A15:8 = 77H, OUT (C),B shows 33H on A15:8, LD (HL),B writes to 4000H | C6-03..C6-07 | written |
| §5: IFF reset: INT held low for 4 instructions after reset is not taken (IFF was 1 before), and INT is released before the second reset (§5 item 4) | C6-09 | written |
| §5: interrupt mode reset to 0 (IM 2 before; INTA then runs mode 0: 12 T and RST 38H, not mode 2's 19 T) | C6-09 | written |
| two resets in a row | C6-08 | written |
| reset during a memory write cycle | **not covered**: the spec doesn't say whether an aborted write reaches memory | - |

## §8 interrupts (C4, chip-z80#64)
INTA data comes from `vec.hex` per case (the harness reads it per half): FFH by default (RST 38H); other values are noted per row. Handlers are tiny and end in HALT/RETN/RETI; results of
IFF2 are shown through `LD A,I` / `LD A,R` + `JP PE,nn` (the next fetch address on `a` shows P/V) and `OUT (n),A`. Every case is also replayed on `ref/refz80.py` per instruction, including
IFF1, IFF2, IM, halted and P/V after each step and what the INT/NMI samples saw (`logs/z80-bus-crosscheck.log`: 26 C4 cases, AGREE).

| Spec behaviour | Test | Status |
|---|---|---|
| §8.1 EI: INT not accepted at the end of EI, accepted at the end of the instruction after it | C4-01 | written, run |
| §8.4 item 5 / §8.1: EI;EI restarts the delay | C4-02 | written, run |
| §8.1 DI row; §8.4 item 5: DI visible to its own sample (INT pending at DI's end not taken) | C4-03, C4-13 (P/V after DI) | written, run |
| §8.4 item 5 / §8.1: RETN IFF1 <- IFF2 visible to its own sample (INT pending at RETN's end taken, no delay) | C4-04 | written, run |
| §8.1 NMI row: IFF1 = 0, IFF2 keeps the old IFF1 (with IFF1 = 1 and with IFF1 = 0) | C4-05, C4-06 | written, run |
| §8.1 RETN row: IFF1 <- IFF2 (both values; INT held low after the return) | C4-05, C4-06 | written, run |
| §8.1 RETI row: IFF unchanged (directed test): IFF1 stays 0 and IFF2 stays 1 after NMI + RETI | C4-07 | written, run |
| §8.1 INT row: IFF1 = IFF2 = 0 on acceptance (seen by LD A,I in the handler; modes 1 and 2) | C4-08, C4-11 | written, run |
| §8.1 LD A,I / LD A,R: P/V = IFF2 (both polarities, both opcodes) | C4-05, C4-06, C4-13 | written, run |
| §8.1 LD A,I / LD A,R: P/V = IFF2 as before an interrupt accepted at the instruction's own end | C4-14 (A,I), C4-15 (A,R) | written, run |
| §8.2 / §4.6 NMI: 11 T = OCF(5) SWH SWL, data byte ignored, PC not advanced, pushed PC, 0066H; R counts the M1 (§6.3) | C4-04..C4-07, C4-16..C4-20 | written, run |
| §8.4 item 5: EI's delay does not apply to NMI | C4-19 | written, run |
| §8.4 item 6 rules 1, 3: NMI edge-triggered; held low gives one response; a new falling edge gives another | C4-16 | written, run |
| §8.4 item 6 rules 4, 5: an edge during the response stays pending; the first handler instruction always runs | C4-18, C4-25 | written, run |
| §8.4 item 6 rule 6 / §4.6: NMI beats INT at the same sample; INT (level) taken after the handler's RETN | C4-17, C4-20 | written, run |
| §8.2 INT mode 0: RST p only, INTA(6) SWH SWL = 12 T (RST 38H, 10H, 28H) | C4-01..C4-04, C4-09, C4-10 | written, run |
| §8.2 INT mode 1: INTA(7) SWH SWL = 13 T, 0038H, bus byte ignored (C9 on the bus) | C4-08, C4-14, C4-15, C4-17, C4-20, C4-22, C4-24, C4-26 | written, run |
| §8.2 INT mode 2: INTA(7) SWH SWL MRL MRH = 19 T, pointer {I, vector}, low byte first (vectors 40H and FEH) | C4-11, C4-12 | written, run |
| §8.4 item 4: BUSRQ low at the sample blocks INT and NMI; NMI stays pending, INT sampled again | C4-20 (and C5-17 for INT alone), C4-26 | written, run |
| §8.4 item 7: INT withdrawn before the sample is never seen | C4-21 | written, run |
| §4.7 / §6.3 HALT items 1-3: halted M1s, HALT exit by INT (IFF1 = 1) and by NMI (IFF1 = 0), INT with IFF1 = 0 does not exit | C4-22, C4-23 (and C2-08) | written, run |
| §4.7 HALT's own M1 accepting an interrupt (SPEC-GAP 3, chip-z80#18/#24/#31) | C4-24, C4-25, C4-26 | written, run |
| §8.2 mode 0 with a multi-byte instruction, mode 2 with vector bit 0 = 1 | **not specified** (spec §8.2): no test | - |
| §8.4 item 5, interrupt between iterations of a block instruction | **out of scope**: per-opcode (decision 7), C8 | - |
| NMI latch timing at the edge where `nmi_n` falls inside the same T state as the sample (§8.3) | **not covered**: stimulus rule (§8.4 item 7) puts `nmi_n` changes at a T1H, at least 2 edges before any sample | - |

## Spec points found while writing these (see the issue filed for Igris)
1. **Stimulus rule vs BUSRQ release (§8.4 item 7).** `busrq_n` may change "only at the edge that starts a T1H", but a bus request has no T1H, so it could never
   be released. The tests release it at the rising edge of a Tx state, and a request lasts ≥ 2 Tx (a 1-Tx request would need the release at the last T of the previous
   cycle, which is neither). Also, `busrq_n` going 0 is placed at a T1H, which is a legal point.
2. **Reset boundaries (§5 items 2-4).** "From the second T state of reset on" and "the first rising edge at which `reset_n` is sampled 1" don't say what the pins do in the
   halves between `reset_n` changing and being sampled. The expected traces don't compare anything in the first reset T state (halves E0, E0+1) or in the two halves after release
   (only `m1_n`, `halt_n`, `busak_n` = 1), and put T1H at E+2 when `reset_n` rose at the rising edge E.
3. **Tw rows (§4.1, §4.2).** The spec says Tw "repeats" the T2L row (M1) and that Tw sits between T2 and T3 (memory). The tests use the T2L row for Tw in memory cycles too (WR low).
4. **§4.3 `d_oe` column** is headed "(out)": taken as 0 for IN, 1 from T1L for OUT.
5. **EI delay (§8.1 vs §8.4 item 5)** is Beru's point 1; settled in spec v1 (end of EI blocked, end of the next instruction allowed): C4-01/02 test exactly that.
6. **Uninitialised A.** §5 doesn't reset A, so a test that shows A on the pins must load it first (C4-24 did not at first and the RTL's power-up A showed through: test bug, fixed).
