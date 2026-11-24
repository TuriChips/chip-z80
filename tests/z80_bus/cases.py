#!/usr/bin/env python3
"""Z80 bus-cycle test cases (C2 basic cycles, C3 WAIT, C5 BUSRQ/BUSAK, C6 reset).

Builds, for every case, tests/z80_bus/vectors/<id>/{prog.hex,prog1.hex,prog2.hex,stim.hex,exp.hex,mask.hex} and
vectors/cases.txt (read by tb/z80_bus/tb.sv), then cross-checks the instruction stream against Beru's ref/refz80.py
and writes logs/z80-bus-crosscheck.log. Expected values come from docs/z80/spec.md (TuriChips/turichips 696e137)
via tests/z80_bus/zbus.py; the case table below cites the spec lines each case exercises.

    python3 tests/z80_bus/cases.py            # build + cross-check
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "ref"))
import zbus  # noqa: E402
from zbus import Stim, Run, PINS, io_data, INTVEC  # noqa: E402

CASES = []


def case(cid, spec, desc, tail, segs, stim=None, plan=None, txplan=None, banks=None, passes=0):
    """tail = halves to run after the last pass reaches HALT; passes = resets after power-up."""
    CASES.append(dict(id=cid, spec=spec, desc=desc, tail=tail, segs=segs, stim=stim or powerup(Stim()), plan=plan,
                      txplan=txplan, banks=banks or {}, passes=passes))


def powerup(stim, E=8):
    stim.set(E, "reset", 1)
    return stim


def prog(*chunks, org=0):
    """chunks are bytes/lists; returns segments [(addr, bytes)]."""
    b = bytearray()
    for c in chunks:
        b += bytes(c)
    return [(org, bytes(b))]


NOP, HALT, EI, DI = 0x00, 0x76, 0xFB, 0xF3
B, C, D, E, H, L, A = 0, 1, 2, 3, 4, 5, 7


def ld_r_n(r, n): return [0x06 | r << 3, n]
def ld_dd_nn(p, nn): return [0x01 | p << 4, nn & 255, nn >> 8]
def ld_r_r(d, s): return [0x40 | d << 3 | s]
def ld_r_hl(r): return [0x46 | r << 3]
def ld_hl_r(r): return [0x70 | r]
def ld_hl_n(n): return [0x36, n]
def ld_a_nn(nn): return [0x3A, nn & 255, nn >> 8]
def ld_nn_a(nn): return [0x32, nn & 255, nn >> 8]
def ld_hl_mem(nn): return [0x2A, nn & 255, nn >> 8]
def ld_mem_hl(nn): return [0x22, nn & 255, nn >> 8]
def out_n_a(n): return [0xD3, n]
def in_a_n(n): return [0xDB, n]
def in_r_c(r): return [0xED, 0x40 | r << 3]
def out_c_r(r): return [0xED, 0x41 | r << 3]
LD_I_A, LD_R_A, LD_A_I, LD_A_R = [0xED, 0x47], [0xED, 0x4F], [0xED, 0x57], [0xED, 0x5F]
def im(m): return [0xED, {0: 0x46, 1: 0x56, 2: 0x5E}[m]]




def plan_for(waits=None, neg=None, busrq=None, int_low=None, resets=None, int_high=None):
    """Keys are (kind, occurrence) in pass 0 or (pass, kind, occurrence); kind is the M-cycle kind (OCF OD MR MW PR PW INTA) or 'HM1'
    for halted opcode fetches (HALT's own M1 is HM1 #0).
    waits {key: k}: k WAIT states in that M cycle (low from T2H for memory/M1, from Tw*H for I/O).
    neg {key}: WAIT low only at halves that are never sampled (T1; T1-T2 for I/O), so no wait state may appear.
    busrq {key}: BUSRQ low from that cycle's T1H (released by txplan). int_low {key}: INT low from that cycle's T1H (released at the INTA's T1H).
    resets {key: (offset_halves, length_halves, bank)}: reset_n low from h0+offset for `length` halves, memory bank swapped at release."""
    norm = lambda d: {(k if len(k) == 3 else (0,) + k): v for k, v in (d or {}).items()}
    waits, neg, busrq, resets = norm(waits), norm(neg), norm(busrq), norm(resets)
    int_low = {(k if len(k) == 3 else (0,) + k) for k in (int_low or ())}
    int_high = {(k if len(k) == 3 else (0,) + k) for k in (int_high or ())}
    count = {}

    def plan(n, c, h0, st, run):
        kinds = [c["k"]] + (["HM1"] if c.get("halt") else [])
        if c["k"] == "INTA":
            st.set(h0, "int", 1)
        for k in kinds:
            occ = count.get((run.pass_no, k), 0)
            count[(run.pass_no, k)] = occ + 1
            key = (run.pass_no, k, occ)
            io = k in ("PR", "PW")
            if key in waits:
                w = waits[key]
                s = h0 + (4 if io else 6 if k == "INTA" else 2)
                st.set(s, "wait", 0)
                st.set(s + 2 * w, "wait", 1)
            elif key in neg:
                st.set(h0, "wait", 0)
                st.set(h0 + (4 if io else 2), "wait", 1)
            if key in busrq:
                st.set(h0, "busrq", 0)
            if key in int_low:
                st.set(h0, "int", 0)
            if key in int_high:
                st.set(h0, "int", 1)
            if key in resets:
                off, ln, bank = resets[key]
                st.set(h0 + off, "reset", 0)
                st.set(h0 + off + ln, "reset", 1)
                if bank:
                    st.banks.append((h0 + off + ln, bank))
    return plan


def txplan_for(ntx):
    """Release BUSRQ at the rising edge of Tx number ntx-2, so the CPU sees it at the next rising edge and the bus request lasts ntx
    Tx states (ntx >= 2). The spec lets busrq_n change only at a T1H (§8.4 item 7) but a bus request has no T1H: see coverage.md, spec finding F1."""
    def tx(e, j, st):
        if j == ntx - 2:
            st.set(e, "busrq", 1)
    return tx


def pad(b, n=0x40):
    return bytes(b) + bytes(n - len(b))


# ----------------------------------------------------------------------------------------------- C2
case("C2-01-nop-fetch", "§4.1 table (every half), §4.0 inactive defaults; §6.3 R rule 1-2",
     "8 NOPs: M1 per half T state, refresh address {I=00,R}, R counts 0..7 after reset",
     20, prog([NOP] * 8, [HALT]))
case("C2-02-ld-reg-fetch", "§4.1 (LD r,n = OCF+OD; LD r,r' = OCF); §4.2 read rows for the operand; §6.1 8-bit and 16-bit load groups",
     "LD r,n; LD r,r'; LD dd,nn: opcode fetch then operand reads, PC on the bus for each",
     20, prog(ld_r_n(B, 0x11), ld_r_n(C, 0x22), ld_r_r(D, B), ld_r_r(E, C), ld_dd_nn(2, 0x1234), ld_dd_nn(3, 0x8000),
              ld_r_n(A, 0x5A), [NOP, HALT]))
case("C2-03-refresh-I", "§4.1 'Refresh address = {I, R}'; §6.3 R rule 1 (prefix counts: ED and its opcode add 2), rule 3; §6.1 LD I,A = OCF(4) OCF(5) with the lengthened-cycle rule",
     "LD A,5A; LD I,A; NOPs: refresh address {5A,R}; T5 of LD I,A carries no refresh and no compared address",
     20, prog(ld_r_n(A, 0x5A), LD_I_A, [NOP] * 5, ld_r_n(A, 0xFD), LD_R_A, [NOP] * 5, [HALT]))
case("C2-04-refresh-R7", "§4.1 decision A7 = R bit 7; §6.3 R rule 1 (R7 unchanged, R6:0 wraps mod 128), rule 3 (LD R,A, LD A,R)",
     "R loaded with FA, NOPs run R through FF -> 80 (bit 7 kept, low 7 bits wrap); LD A,R then OUT shows R on A15:8; LD A,I too",
     20, prog(ld_r_n(A, 0xFA), LD_R_A, [NOP] * 8, LD_A_R, out_n_a(0x20), ld_r_n(A, 0x3C), LD_I_A, LD_A_I, out_n_a(0x21), [HALT]))
MEMDATA = [(0x1234, bytes([0xC3])), (0x2000, bytes([0x3C])), (0x2001, bytes([0xA5])), (0x3000, bytes([0x81])),
           (0x3100, bytes([0x42])), (0x2200, bytes([0x34, 0x12]))]
case("C2-05-mem-read", "§4.2 read table (every half); §6.1 LD r,(HL), LD A,(BC), LD A,(DE), LD A,(nn), LD HL,(nn)",
     "memory reads at several addresses; each result then shown through an OUT (n),A so a wrong data capture shows up on A15:8",
     20, prog(ld_dd_nn(2, 0x1234), ld_r_hl(B), ld_r_r(A, B), out_n_a(0x2F), ld_dd_nn(0, 0x2000), [0x0A], out_n_a(0x30),
              ld_dd_nn(1, 0x3000), [0x1A], out_n_a(0x31), ld_a_nn(0x3100), out_n_a(0x32),
              ld_hl_mem(0x2200), ld_r_r(A, H), out_n_a(0x33), [HALT]) + MEMDATA)
case("C2-06-mem-write", "§4.2 write table (WR mid-T2, d_oe from T1L, d_oe low at the next T1H); §6.1 LD (HL),r / (HL),n / (BC),A / (DE),A / (nn),A / (nn),HL",
     "memory writes of several data values, then read back with LD A,(nn) and OUT",
     20, prog(ld_dd_nn(2, 0x4000), ld_r_n(B, 0x66), ld_hl_r(B), ld_hl_n(0x99), ld_r_n(A, 0xC4), ld_dd_nn(0, 0x4010),
              [0x02], ld_dd_nn(1, 0x4020), [0x12], ld_nn_a(0x4030), ld_mem_hl(0x4040), ld_a_nn(0x4000), out_n_a(0x40),
              ld_a_nn(0x4041), out_n_a(0x41), [HALT]))
case("C2-07-io", "§4.3 table (IORQ/RD/WR fall at T2's rising edge, automatic Tw*, d_oe from T1L for OUT); §6.1 A15:8 = A for the (n) forms, B for the (C) forms",
     "IN A,(n); OUT (n),A; IN r,(C); OUT (C),r with A and B different, so A15:8 shows which register is on the bus",
     20, prog(ld_r_n(A, 0x12), ld_r_n(B, 0x34), ld_r_n(C, 0x56), in_a_n(0x77), out_n_a(0x88), in_r_c(D), out_c_r(B),
              out_c_r(D), in_r_c(A), out_n_a(0x99), [HALT]))
case("C2-08-halt", "§4.7 (halt_n falls at T4L of HALT's M1; halted M1s with refresh at HALT+1; data ignored), §6.3 HALT items 1-2, R counts halted M1s",
     "NOP; HALT; then 6 halted M1s: the §4.1 rows at address HALT+1, halt_n low",
     4 * 2 * 6, prog([NOP, NOP, HALT, 0xAA, 0xBB]))

# ----------------------------------------------------------------------------------------------- C3
WPROG = prog(ld_r_n(A, 0x00), ld_dd_nn(2, 0x2000), [NOP], ld_r_hl(B), ld_hl_r(B), in_a_n(0x40), out_n_a(0x41), ld_a_nn(0x2000), [HALT]) + \
    [(0x2000, bytes([0x5C]))]
for k in (1, 2, 3):
    case(f"C3-0{k}-wait-m1", "§4.1 T2L row (Tw repeats it); §4.0 WAIT sampled at the edge starting T2L and each TwL",
         f"{k} wait state(s) in the M1 of NOP, of LD B,(HL) and in both M1s of the ED prefix of LD I,A",
         20, prog(ld_dd_nn(2, 0x2000), [NOP], ld_r_hl(B), ld_r_n(A, 0x00), LD_I_A, [NOP, HALT]) + [(0x2000, bytes([0x5C]))],
         plan=plan_for(waits={("OCF", 1): k, ("OCF", 2): k, ("OCF", 3): k, ("OCF", 4): k}))
    case(f"C3-0{3 + k}-wait-mem", "§4.2 (Tw between T2 and T3, WAIT at T2L, WR stays low in Tw; read data taken at T3L); §4.0",
         f"{k} wait state(s) in an operand read, a memory read, a memory write and the last cycle of LD A,(nn)",
         20, WPROG, plan=plan_for(waits={("OD", 0): k, ("MR", 0): k, ("MW", 0): k, ("MR", 1): k}))
    case(f"C3-0{6 + k}-wait-io", "§4.3 (one automatic Tw*, then Tw while WAIT is 0; WAIT sampled at the edge starting Tw*L)",
         f"{k} extra wait state(s) on top of Tw* in IN and OUT",
         20, WPROG, plan=plan_for(waits={("PR", 0): k, ("PW", 0): k}))
case("C3-10-wait-unsampled", "§4.0 WAIT only sampled at T2L/TwL (I/O: Tw*L): a low that is gone before the sample adds nothing",
     "WAIT low during T1 only (M1 and memory) and during T1-T2 only (I/O): no wait state may appear",
     20, WPROG,
     plan=plan_for(neg={("OCF", 2): 1, ("OCF", 3): 1, ("OD", 1): 1, ("MR", 0): 1, ("MW", 0): 1, ("PR", 0): 1, ("PW", 0): 1}))
case("C3-11-wait-mixed", "§4.0-§4.3: waits in several cycles of one instruction",
     "LD A,(nn) with 1, 2 and 3 wait states in its M1, ODL and MR cycles; OUT with 2 extra waits",
     20, WPROG, plan=plan_for(waits={("OCF", 6): 1, ("OD", 3): 2, ("OD", 4): 1, ("MR", 1): 3, ("PW", 0): 2}))

INTPROG = prog(ld_dd_nn(3, 0x4100), [EI] + [NOP] * 7 + [HALT]) + [(0x38, bytes([HALT]))]
for k in (1, 2):
    case(f"C3-1{1 + k}-wait-inta", "§4.5 (WAIT sampled at the edge starting Tw*2L; user wait states follow the two Tw*, Figure 4.0-5B), §8.2 mode 0",
         f"{k} user wait state(s) in the interrupt-acknowledge M1 (after the two automatic Tw*)",
         20, INTPROG, plan=plan_for(int_low={("OCF", 4)}, waits={("INTA", 0): k}))

# ----------------------------------------------------------------------------------------------- C5
BPROG = prog(ld_r_n(A, 0x00), ld_dd_nn(2, 0x2000), [NOP], ld_r_hl(B), ld_hl_r(B), in_a_n(0x40), out_n_a(0x41), ld_a_nn(0x2000), [NOP, HALT]) + \
    [(0x2000, bytes([0x5C]))]
bi = 0
for kind, occ, label in (("OCF", 2, "M1 of a NOP"), ("OCF", 3, "M1 of LD B,(HL)"), ("MR", 0, "memory read"), ("MW", 0, "memory write"),
                         ("PR", 0, "I/O read"), ("PW", 0, "I/O write"), ("OD", 5, "operand read inside LD A,(nn)")):
    for ntx in (2, 3):
        bi += 1
        case(f"C5-{bi:02d}-busrq-{kind.lower()}{occ}-tx{ntx}",
             "§4.4 (sample at the edge starting the last T; floats from the next rising edge; BUSAK low with it; Tx count; BUSAK high at the falling edge after the release is sampled; bus driven from the next rising edge); §8.4 item 4",
             f"BUSRQ low from T1H of the {label}, {ntx} Tx states: outputs float, busak_n low, then the program carries on",
             20, BPROG, plan=plan_for(busrq={(kind, occ): 1}), txplan=txplan_for(ntx))
case("C5-15-busrq-wait", "§4.4 + §4.0: BUSRQ sampled at the last T, which comes after the wait states",
     "BUSRQ low from T1H of a memory read that has 2 wait states: floating starts only after T3",
     20, BPROG, plan=plan_for(waits={("MR", 0): 2}, busrq={("MR", 0): 1}), txplan=txplan_for(2))
case("C5-16-busrq-twice", "§4.4: bus requests in consecutive cycles",
     "BUSRQ low at T1H of two consecutive M1s, each released after 2 Tx",
     20, BPROG, plan=plan_for(busrq={("OCF", 2): 1, ("OCF", 3): 1}), txplan=txplan_for(2))
case("C5-17-no-int-during-busrq", "§4.4 / §4.5: INT is ignored if BUSRQ is low at the sample; mode-0 INTA §4.5, §8.2 (RST 38H = 12 T), R counts the INTA M1 (§6.3)",
     "EI; NOP; NOP; with INT and BUSRQ both low at the third NOP's T1H: no INTA at the end of that NOP, the bus is released, then INT (still low) is taken at the end of the next instruction",
     20, INTPROG, plan=plan_for(busrq={("OCF", 4): 1}, int_low={("OCF", 4)}), txplan=txplan_for(2))
case("C5-18-int-without-busrq", "§4.5, §8.2, §6.3: positive case for C5-17: same program, BUSRQ never asserted, INT taken at the end of the third NOP",
     "EI; NOP; NOP; INT low at the third NOP's T1H: INTA M1 (T1 T2 Tw* Tw* T3 T4, vector FF), PC pushed (two writes), handler at 0038H",
     20, INTPROG, plan=plan_for(int_low={("OCF", 4)}))

# ----------------------------------------------------------------------------------------------- C6
PASS1 = prog(ld_r_n(A, 0x5A), LD_I_A, ld_r_n(A, 0x77), ld_r_n(B, 0x33), ld_r_n(C, 0x44), ld_dd_nn(2, 0x4000), ld_dd_nn(3, 0x4100),
             im(2), [EI], [NOP] * 4, [HALT])
PASS2 = [(0, pad(bytes(out_n_a(0x10) + out_c_r(B) + ld_hl_r(B) + ld_r_hl(D) + ld_r_r(A, D) + out_n_a(0x11) + [HALT])))]
case("C6-01-powerup-min", "§5 items 3-4: reset held 3 T (6 halves, the minimum); first M1 at the first rising edge at which reset_n is sampled 1, address 0000H; I and R = 0 in its refresh address",
     "power-up reset of 6 halves, then NOPs", 20, prog([NOP] * 6, [HALT]), (lambda s: (s.set(6, "reset", 1), s)[1])(Stim()))
case("C6-02-powerup-long", "§5 items 2-4: a longer reset (22 halves)",
     "power-up reset of 22 halves, then LD A,n; OUT", 20, prog(ld_r_n(A, 0x21), out_n_a(0x10), [HALT]),
     (lambda s: (s.set(22, "reset", 1), s)[1])(Stim()))
for ph, tn in ((0, "T1"), (1, "T2"), (2, "T3"), (3, "T4")):
    case(f"C6-0{3 + ph}-reset-in-nop-{tn}", "§5 items 1, 2, 4: R and I reset (refresh address {00,00} after); A, B, C, H, L, SP kept ('no exemption window'); first M1 at 0000H; abort at T1..T4 of an M1",
         f"reset asserted at {tn} of a NOP (after LD I,A, LD A/B/C/HL/SP, IM 2, EI), held 8 halves; the second program shows A, B, C, HL and memory kept",
         20, PASS1, banks={1: PASS2}, passes=1, plan=plan_for(resets={("OCF", 12): (2 * ph, 8, 1)}))
case("C6-07-reset-from-halt", "§5 item 4 + §6.3 HALT item 4: reset ends a halt; halt_n = 1 compared from the second reset T state",
     "reset while halted (halted M1s running, halt_n low), then the second program",
     20, PASS1, banks={1: PASS2}, passes=1, plan=plan_for(resets={("HM1", 3): (0, 8, 1)}))
case("C6-08-reset-twice", "§5: two resets in a row, each restoring I = R = 0 and PC = 0",
     "reset in the NOP run, a short second program, a second reset into a third program",
     20, PASS1, banks={1: PASS2, 2: PASS2}, passes=2, plan=plan_for(resets={("OCF", 12): (0, 8, 1), (1, "OCF", 3): (4, 6, 2)}))
PASS_IFF = [(0, pad([NOP] * 10 + [HALT]))]
PASS_IM = [(0, pad(ld_dd_nn(3, 0x4100) + [EI] + [NOP] * 6 + [HALT])), (0x38, bytes([HALT]))]
case("C6-09-reset-iff-im", "§5 / §3.0 reset: IFF1/IFF2 = 0 and IM = 0 (observed: INT ignored with IFF clear; then mode-0 INTA, 12 T, not IM 2's 19 T); §4.5, §8.2",
     "pass 1 does IM 2 and EI; after reset INT is low from the first T1H until the fifth M1 but not taken (IFF = 0); after a second reset EI; NOP; NOP; INT low at the third NOP's T1H is taken as IM 0 (RST 38H, 12 T)",
     20, PASS1, banks={1: PASS_IFF, 2: PASS_IM}, passes=2,
     plan=plan_for(resets={("OCF", 12): (0, 8, 1), (1, "OCF", 5): (0, 8, 2)}, int_low={(1, "OCF", 0), (2, "OCF", 4)}, int_high={(1, "OCF", 4)}))

# ================================================================================================= driver
def build(cs):
    mem = bytearray(65536)
    for a, d in cs["segs"]:
        mem[a:a + len(d)] = d
    run = Run(mem, cs["banks"], cs["stim"], cs["plan"], cs["txplan"])
    mark = {}

    def done(r):
        if r.pass_no >= cs["passes"] and r.cpu.halted and not r.queue and "h" not in mark:
            mark["h"] = len(r.rows)
        return "h" in mark and len(r.rows) >= mark["h"] + cs["tail"]
    run.run(done)
    del run.rows[mark["h"] + cs["tail"]:]
    return run


def pack(r):
    """36-bit vector + mask, layout in tb/z80_bus/tb.sv."""
    v = m = 0
    fields = [("a", 20, 16), ("d_out", 12, 8), ("m1", 11, 1), ("mreq", 10, 1), ("iorq", 9, 1), ("rd", 8, 1), ("wr", 7, 1),
              ("rfsh", 6, 1), ("halt", 5, 1), ("busak", 4, 1), ("bus_oe", 3, 1), ("d_oe", 2, 1)]
    for name, lo, w in fields:
        x = r[name]
        if x is not None:
            v |= x << lo
            m |= ((1 << w) - 1) << lo
    return v, m


def write_vectors(cs, run):
    d = os.path.join(HERE, "vectors", cs["id"])
    os.makedirs(d, exist_ok=True)

    def hexfile(name, segs):
        with open(os.path.join(d, name), "w") as f:
            for a, data in segs:
                f.write(f"@{a:04X}\n")
                for i in range(0, len(data), 16):
                    f.write(" ".join(f"{b:02X}" for b in data[i:i + 16]) + "\n")
    hexfile("prog.hex", cs["segs"])
    for k, segs in cs["banks"].items():
        hexfile(f"prog{k}.hex", segs)
    evs = cs["stim"].events()
    with open(os.path.join(d, "stim.hex"), "w") as f:
        for h, w, b, i, n, r, bank in evs:
            f.write(f"{h << 8 | w | b << 1 | i << 2 | n << 3 | r << 4 | bank << 5:08X}\n")
    st = cs["stim"]
    with open(os.path.join(d, "inp.hex"), "w") as f:       # the input values each half must carry: the harness checks its own stimulus
        for h in range(len(run.rows)):
            v = [st.S(sg, h) for sg in ("wait", "busrq", "int", "nmi", "reset")]
            f.write(f"{v[0] | v[1] << 1 | v[2] << 2 | v[3] << 3 | v[4] << 4:02X}\n")
    with open(os.path.join(d, "exp.hex"), "w") as fe, open(os.path.join(d, "mask.hex"), "w") as fm:
        for r in run.rows:
            v, m = pack(r)
            fe.write(f"{v:09X}\n")
            fm.write(f"{m:09X}\n")
    return len(evs), len(run.rows)


def crosscheck(cs, run, log):
    """Replay the generator's instruction stream on Beru's ref model. Compares per step: T states, PC, I, R, I/O port accesses and the
    memory image. A disagreement is a finding (file it as Igris: spec or Beru: model), never silently followed."""
    import refz80
    mem = bytearray(65536)
    for a, d in cs["segs"]:
        mem[a:a + len(d)] = d
    z = refz80.Z80(mem=mem)
    ports = []
    z.io_in = lambda p: (ports.append(("in", p, io_data(p))), io_data(p))[1]
    z.io_out = lambda p, v: ports.append(("out", p, v))
    z.int_data = lambda: INTVEC
    bad = 0
    nstep = 0
    for st in run.steps:
        if st[0] == "reset":
            z.reset()
            if st[1] is not None:
                for a, d in cs["banks"][st[1]]:
                    z.mem[a:a + len(d)] = d
            continue
        _, name, T, pc, i, r, cyc, intl = st
        ports.clear()
        z.int_line = intl
        try:
            t = z.step()
        except Exception as e:                           # noqa: BLE001
            log.write(f"  {cs['id']} step {nstep} {name}: ref raised {type(e).__name__}: {e}\n")
            bad += 1
            break
        exp_ports = [("in" if c["k"] == "PR" else "out", c["a"], c["data"]) for c in cyc if c["k"] in ("PR", "PW")]
        got = (t, z.pc, z.i, z.r, ports[:])
        want = (T, pc, i, r, exp_ports)
        if got != want:
            bad += 1
            log.write(f"  {cs['id']} step {nstep} {name}: DISAGREE ref (T,pc,i,r,ports)={got} trace={want}\n")
        nstep += 1
    if bytes(z.mem) != bytes(run.mem):
        bad += 1
        diff = [a for a in range(65536) if z.mem[a] != run.mem[a]][:5]
        log.write(f"  {cs['id']}: memory image differs at {[hex(a) for a in diff]}\n")
    return nstep, bad


def main():
    os.makedirs(os.path.join(HERE, "vectors"), exist_ok=True)
    out, total_bad = [], 0
    logp = os.path.join(ROOT, "logs", "z80-bus-crosscheck.log")
    os.makedirs(os.path.dirname(logp), exist_ok=True)
    only = sys.argv[1:]
    with open(logp, "w") as log:
        log.write("Z80 bus-cycle expected traces (tests/z80_bus/cases.py) vs ref/refz80.py: per-instruction T states, PC, I, R,\n"
                  "I/O port accesses (address incl. A15:8, data) and the final memory image. 'DISAGREE' lines are findings.\n\n")
        for cs in CASES:
            if only and cs["id"] not in only:
                continue
            run = build(cs)
            nev, nrows = write_vectors(cs, run)
            nstep, bad = crosscheck(cs, run, log)
            total_bad += bad
            line = f"{cs['id']}: {nrows} halves, {nev} stim events, {nstep} steps checked vs ref, {'AGREE' if not bad else f'{bad} DISAGREEMENTS'}"
            log.write(line + "\n")
            print(line)
            out.append(f"{cs['id']} {nrows} {nev}")
        if not only:
            with open(os.path.join(HERE, "vectors", "cases.txt"), "w") as f:
                f.write("\n".join(out) + "\n")
        log.write(f"\n{len(out)} cases, {total_bad} disagreements\n")
    print(f"{len(out)} cases, {total_bad} disagreements; log {os.path.relpath(logp, ROOT)}")
    return 1 if total_bad else 0


if __name__ == "__main__":
    sys.exit(main())
