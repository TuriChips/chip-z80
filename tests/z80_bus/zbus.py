"""Expected pin traces for the Z80 bus-cycle tests (C2 basic, C3, C5, C6), built from docs/z80/spec.md
(TuriChips/turichips 696e137) only. Nothing here reads RTL. Section numbers below are that spec's.

A trace is a list of rows, one per half T state (§4.0: model clock = half T state, row 0 = first rising
edge). A row maps pin -> 0/1/int, or None = not compared. Inputs follow §8.4 item 7: they change at a
model edge and are seen only by samples at later edges, so S(sig, h) = the value held during half h and
a sample taken at the edge that starts half h sees S(sig, h-1).
"""
import bisect

PINS = ["a", "d_out", "m1", "mreq", "iorq", "rd", "wr", "rfsh", "halt", "busak", "bus_oe", "d_oe"]
IO_XOR = 0xA5          # harness: IN data = low byte of address ^ A5 (tb/z80_bus/z80_system.sv)
INTVEC = 0xFF          # harness: data on the bus during INTA = RST 38H (mode 0, §8.2)
B_, C_, D_, E_, H_, L_, A_ = 0, 1, 2, 3, 4, 5, 7


def io_data(addr):
    return (addr & 0xFF) ^ IO_XOR


class Stim:
    """Input stimulus: per-signal change lists. Initial: reset_n = 0, everything else 1 (§5 item 4)."""
    SIGS = ["wait", "busrq", "int", "nmi", "reset"]

    def __init__(self):
        self.ev = {s: [(-1, 0 if s == "reset" else 1)] for s in self.SIGS}
        self.banks = []                      # (h, bank) memory image reloads, applied at edge h

    def set(self, h, sig, v):
        e = self.ev[sig]
        assert h >= e[-1][0], f"{sig} event at {h} is before {e[-1]}"
        if h == e[-1][0]:
            e.pop()
        if e[-1][1] != v:
            e.append((h, v))

    def S(self, sig, h):
        e = self.ev[sig]
        return e[bisect.bisect_right([x[0] for x in e], h) - 1][1]

    def events(self):
        """Merged event list [(h, wait, busrq, int, nmi, reset, bank)], one entry per h with a change."""
        hs = sorted({h for s in self.SIGS for h, _ in self.ev[s][1:]} | {h for h, _ in self.banks})
        out = []
        for h in hs:
            vals = [self.S(s, h) for s in self.SIGS]
            bank = dict(self.banks).get(h, 0)
            out.append((h, *vals, bank))
        return out


# ------------------------------------------------------------------------------------- mini CPU
class Mini:
    """Just enough Z80 to know each instruction's M cycles (§6.1: types from MK3880 p.85), bus addresses and
    data. Opcodes: NOP HALT EI DI IM LD r,r' LD r,n LD dd,nn LD r,(HL) LD (HL),r LD (HL),n LD A,(BC/DE/nn) LD (BC/DE/nn),A
    LD HL,(nn) LD (nn),HL IN/OUT (n)/(C) LD I,A LD R,A LD A,I LD A,R. No flags."""

    def __init__(self, mem):
        self.mem = mem
        self.reg = [0] * 8
        self.sp = 0
        self.reset()

    def reset(self):                          # §5: PC, I, R, IFF, IM only
        self.pc = self.i = self.r = 0
        self.iff1 = self.iff2 = 0
        self.im = 0
        self.halted = False
        self.ei_cnt = 0
        self.pv = None                                        # P/V after LD A,I / LD A,R (= IFF2, §8.1); None = not set by those
        self.vec = INTVEC                                     # byte on the bus in the next INTA (set by the scheduler per case)

    def rp(self, p):
        return self.sp if p == 3 else self.reg[2 * p] << 8 | self.reg[2 * p + 1]

    def setrp(self, p, v):
        if p == 3:
            self.sp = v & 0xFFFF
        else:
            self.reg[2 * p], self.reg[2 * p + 1] = (v >> 8) & 255, v & 255

    # one M cycle each; they update state and return the cycle record
    def ocf(self, T=4, ignored=False):
        c = dict(k="OCF", T=T, a=self.pc, ra=self.i << 8 | self.r, data=self.mem[self.pc], halt=self.halted)
        self.r = (self.r & 0x80) | ((self.r + 1) & 0x7F)      # §6.3 R rule 1: +1 per M1, R7 unchanged
        if not ignored:
            self.pc = (self.pc + 1) & 0xFFFF
        return c

    def od(self):
        c = dict(k="OD", T=3, a=self.pc, data=self.mem[self.pc])
        self.pc = (self.pc + 1) & 0xFFFF
        return c

    def mr(self, a):
        return dict(k="MR", T=3, a=a & 0xFFFF, data=self.mem[a & 0xFFFF])

    def mw(self, a, v):
        self.mem[a & 0xFFFF] = v & 255
        return dict(k="MW", T=3, a=a & 0xFFFF, data=v & 255)

    def pr(self, a):
        return dict(k="PR", T=4, a=a, data=io_data(a))

    def pw(self, a, v):
        return dict(k="PW", T=4, a=a, data=v & 255)

    def step(self):
        """Run one instruction (or one halted M1). Returns (name, [cycles])."""
        if self.halted:
            return "HALT-M1", [self.ocf(ignored=True)]
        pc0 = self.pc
        c0 = self.ocf()
        op = c0["data"]
        cy = [c0]
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        p, q = y >> 1, y & 1
        name = f"{op:02X}"
        if op == 0x00:
            name = "NOP"
        elif op == 0x76:
            name = "HALT"
            self.halted = True
            c0["halt"] = True
        elif op == 0xFB:
            name = "EI"
            self.iff1 = self.iff2 = 1
            self.ei_cnt = 1                                   # §8.1/§8.4 item 5: INT blocked at the end of EI only; EI;EI restarts it
        elif op == 0xF3:
            name = "DI"
            self.iff1 = self.iff2 = 0
        elif x == 0 and z == 1 and q == 0:                    # LD dd,nn
            lo = self.od(); hi = self.od(); cy += [lo, hi]
            self.setrp(p, lo["data"] | hi["data"] << 8); name = "LD dd,nn"
        elif x == 0 and z == 6:                               # LD r,n / LD (HL),n
            n = self.od(); cy.append(n)
            if y == 6:
                cy.append(self.mw(self.rp(2), n["data"]))
            else:
                self.reg[y] = n["data"]
            name = "LD r,n"
        elif op in (0x0A, 0x1A):
            m = self.mr(self.rp(p)); cy.append(m); self.reg[A_] = m["data"]; name = "LD A,(rr)"
        elif op in (0x02, 0x12):
            cy.append(self.mw(self.rp(p), self.reg[A_])); name = "LD (rr),A"
        elif op in (0x3A, 0x32, 0x2A, 0x22):
            lo = self.od(); hi = self.od(); cy += [lo, hi]
            nn = lo["data"] | hi["data"] << 8
            if op == 0x3A:
                m = self.mr(nn); cy.append(m); self.reg[A_] = m["data"]
            elif op == 0x32:
                cy.append(self.mw(nn, self.reg[A_]))
            elif op == 0x2A:
                m1 = self.mr(nn); m2 = self.mr(nn + 1); cy += [m1, m2]
                self.reg[L_], self.reg[H_] = m1["data"], m2["data"]
            else:
                cy += [self.mw(nn, self.reg[L_]), self.mw(nn + 1, self.reg[H_])]
            name = {0x3A: "LD A,(nn)", 0x32: "LD (nn),A", 0x2A: "LD HL,(nn)", 0x22: "LD (nn),HL"}[op]
        elif x == 1:                                          # LD r,r' (HALT handled above)
            if z == 6:
                m = self.mr(self.rp(2)); cy.append(m); self.reg[y] = m["data"]; name = "LD r,(HL)"
            elif y == 6:
                cy.append(self.mw(self.rp(2), self.reg[z])); name = "LD (HL),r"
            else:
                self.reg[y] = self.reg[z]; name = "LD r,r'"
        elif op == 0xD3:
            n = self.od(); cy.append(n)
            cy.append(self.pw(self.reg[A_] << 8 | n["data"], self.reg[A_])); name = "OUT (n),A"
        elif op == 0xDB:
            n = self.od(); cy.append(n)
            io = self.pr(self.reg[A_] << 8 | n["data"]); cy.append(io); self.reg[A_] = io["data"]; name = "IN A,(n)"
        elif op == 0xED:
            op2 = self.mem[self.pc]
            x2, y2, z2 = op2 >> 6, (op2 >> 3) & 7, op2 & 7
            ext = op2 in (0x47, 0x4F, 0x57, 0x5F)             # §6.1: OCF(4) OCF(5)
            c1 = self.ocf(5 if ext else 4); cy.append(c1)
            if op2 == 0x47:
                self.i = self.reg[A_]; name = "LD I,A"
            elif op2 == 0x4F:
                self.r = self.reg[A_]; name = "LD R,A"      # §6.3 rule 3: R = A after its own increments
            elif op2 == 0x57:
                self.reg[A_] = self.i; name = "LD A,I"; self.pv = self.iff2
            elif op2 == 0x5F:
                self.reg[A_] = self.r; name = "LD A,R"; self.pv = self.iff2      # R after both of its increments
            elif op2 in (0x46, 0x56, 0x5E):
                self.im = {0x46: 0, 0x56: 1, 0x5E: 2}[op2]; name = f"IM {self.im}"
            elif x2 == 1 and z2 == 0 and y2 != 6:
                io = self.pr(self.rp(0)); cy.append(io); self.reg[y2] = io["data"]; name = "IN r,(C)"; self.pv = None
            elif x2 == 1 and z2 == 1 and y2 != 6:
                cy.append(self.pw(self.rp(0), self.reg[y2])); name = "OUT (C),r"
            elif op2 in (0x45, 0x4D):                         # RETN / RETI: OCF(4) OCF(4) MR(3) MR(3) = 14 T (§6.1)
                lo = self.mr(self.sp); hi = self.mr(self.sp + 1); cy += [lo, hi]
                self.sp = (self.sp + 2) & 0xFFFF
                self.pc = lo["data"] | hi["data"] << 8
                if op2 == 0x45:
                    self.iff1 = self.iff2; name = "RETN"        # §8.1: IFF1 <- IFF2
                else:
                    name = "RETI"                               # §8.1: IFF unchanged
            else:
                raise ValueError(f"ED {op2:02X} not in this subset")
        elif op in (0xC3, 0xE2, 0xEA):                        # JP nn / JP PO,nn / JP PE,nn: OCF OD OD, no extra cycle either way
            lo = self.od(); hi = self.od(); cy += [lo, hi]
            nn = lo["data"] | hi["data"] << 8
            assert op == 0xC3 or self.pv is not None, "JP PO/PE needs P/V set by LD A,I / LD A,R"
            if op == 0xC3 or (op == 0xEA) == bool(self.pv):
                self.pc = nn
            name = {0xC3: "JP nn", 0xE2: "JP PO,nn", 0xEA: "JP PE,nn"}[op]
        else:
            raise ValueError(f"opcode {op:02X} at {pc0:04X} not in this subset")
        return name, cy

    def push_pc(self):
        w1 = self.mw(self.sp - 1, self.pc >> 8); w2 = self.mw(self.sp - 2, self.pc & 255)
        self.sp = (self.sp - 2) & 0xFFFF
        return [w1, w2]

    def inta(self):
        """INT accepted (§4.5, §8.2). Mode 0: INTA(6) SWH SWL = 12 T with RST p on the bus; mode 1: INTA(7) SWH SWL = 13 T, bus ignored;
        mode 2: INTA(7) SWH SWL MRL MRH = 19 T, vector byte on the bus. IFF1 = IFF2 = 0 (§8.1)."""
        self.halted = False
        c0 = dict(k="INTA", T=6 if self.im == 0 else 7, a=self.pc, ra=self.i << 8 | self.r, data=self.vec)
        self.r = (self.r & 0x80) | ((self.r + 1) & 0x7F)
        self.iff1 = self.iff2 = 0
        cy = [c0] + self.push_pc()
        if self.im == 0:
            assert self.vec & 0xC7 == 0xC7, "mode 0 tests insert RST p only (§8.2)"
            self.pc = self.vec & 0x38
            return f"INT0 RST {self.pc:02X}", cy
        if self.im == 1:
            self.pc = 0x38
            return "INT1", cy
        assert self.vec & 1 == 0, "mode 2 vector bit 0 = 0 (§8.2)"
        ptr = self.i << 8 | self.vec
        lo = self.mr(ptr); hi = self.mr(ptr + 1)
        self.pc = lo["data"] | hi["data"] << 8
        return f"INT2 {self.vec:02X}", cy + [lo, hi]

    def nmi(self):
        """NMI accepted (§4.6, §8.2): OCF(5) with the data byte ignored and PC not advanced, SWH, SWL = 11 T; PC = 0066H; IFF1 = 0, IFF2 kept."""
        self.halted = False
        c0 = self.ocf(5, ignored=True)
        c0["nmi"] = True
        self.iff1 = 0
        cy = [c0] + self.push_pc()
        self.pc = 0x66
        return "NMI", cy


# ------------------------------------------------------------------------------------- row builders
def row(**kw):
    r = dict(a=None, d_out=None, m1=1, mreq=1, iorq=1, rd=1, wr=1, rfsh=1, halt=1, busak=1, bus_oe=1, d_oe=0)
    r.update(kw)
    return r


def tx_row(halt):
    return dict(a=None, d_out=None, m1=1, mreq=None, iorq=None, rd=None, wr=None, rfsh=None, halt=halt,
                busak=0, bus_oe=0, d_oe=0)


def cycle_rows(c, h0, S, halt_in, accept=False):
    """Rows of one M cycle starting at half h0 (its T1H), waits taken from S. Returns (rows, index of the H half
    of the last T state, halt_n value after the cycle)."""
    k, rows = c["k"], []
    halt = halt_in
    if k in ("OCF", "INTA"):
        inta = k == "INTA"
        a = c["a"]
        base = dict(a=a, m1=0)
        t2 = dict(base, mreq=1 if inta else 0, rd=1 if inta else 0)
        rows += [row(halt=halt, **dict(base)), row(halt=halt, **dict(t2)), row(halt=halt, **t2), row(halt=halt, **t2)]
        if inta:                                              # §4.5: T1 T2 Tw* Tw* T3 T4, iorq falls at Tw*1L
            rows += [row(halt=halt, a=a, m1=0), row(halt=halt, a=a, m1=0, iorq=0),
                     row(halt=halt, a=a, m1=0, iorq=0), row(halt=halt, a=a, m1=0, iorq=0)]
            hs = h0 + 7                                       # edge starting Tw*2L; user waits repeat the Tw*2 row (§4.5, Figure 4.0-5B)
            while S("wait", hs - 1) == 0:
                rows += [row(halt=halt, a=a, m1=0, iorq=0), row(halt=halt, a=a, m1=0, iorq=0)]
                hs += 2
        else:
            hs = h0 + 3                                       # edge starting T2L (§4.0)
            while S("wait", hs - 1) == 0:                     # Tw: repeats the T2L row, sampled at each TwL
                rows += [row(halt=halt, **t2), row(halt=halt, **t2)]
                hs += 2
        ra = c["ra"]
        t3l = dict(a=ra, m1=1, mreq=0, rfsh=0)
        ex = dict(a=ra, m1=1)
        rows += [row(halt=halt, a=ra, m1=1, rfsh=0), row(halt=halt, **t3l), row(halt=halt, **t3l)]
        if c.get("halt") and not inta:
            halt = 1 if accept else 0                         # §4.7: halt_n falls at the edge starting T4L of HALT's own M1, rises at T4L of the halted M1 whose
                                                              # T4 sample accepts an interrupt; if HALT's own M1 accepts, it never falls (§4.7, chip-z80#24)
        rows += [row(halt=halt, a=ra, m1=1, mreq=1, rfsh=0)]
        for _ in range(c["T"] - 4 if not inta else c["T"] - 6):   # §6.1 lengthened cycles: extra T after T4, a not compared
            rows += [row(halt=halt), row(halt=halt)]
        return rows, len(rows) - 2, halt
    a = c["a"]
    if k in ("MR", "MW", "OD"):
        wr = k == "MW"
        d = c["data"] if wr else None
        r1 = row(halt=halt, a=a)
        r2 = row(halt=halt, a=a, mreq=0, rd=1 if wr else 0, d_oe=1 if wr else 0, d_out=d)
        r3 = dict(r2)
        r4 = dict(r2, wr=0) if wr else dict(r2)
        rows += [r1, r2, r3, r4]
        hs = h0 + 3
        while S("wait", hs - 1) == 0:
            rows += [dict(r4), dict(r4)]
            hs += 2
        rows += [dict(r4), row(halt=halt, a=a, d_oe=1 if wr else 0, d_out=d)]
        return rows, len(rows) - 2, halt
    if k in ("PR", "PW"):
        wr = k == "PW"
        d = c["data"] if wr else None
        io = dict(a=a, iorq=0, rd=1 if wr else 0, wr=0 if wr else 1, d_oe=1 if wr else 0, d_out=d)
        rows += [row(halt=halt, a=a), row(halt=halt, a=a, d_oe=1 if wr else 0, d_out=d)]
        rows += [row(halt=halt, **io)] * 4                    # T2H T2L Tw*H Tw*L
        hs = h0 + 5                                           # edge starting Tw*L
        while S("wait", hs - 1) == 0:
            rows += [row(halt=halt, **io)] * 2
            hs += 2
        rows += [row(halt=halt, **io), row(halt=halt, a=a, d_oe=1 if wr else 0, d_out=d)]
        return [dict(r) for r in rows], len(rows) - 2, halt
    raise ValueError(k)


def dont_care(halt=None, m1=None, busak=None):
    return dict(a=None, d_out=None, m1=m1, mreq=None, iorq=None, rd=None, wr=None, rfsh=None, halt=halt, busak=busak,
                bus_oe=None, d_oe=None)


def reset_rows(E0, E):
    """§5 items 2, 4: T state 1 of reset and the two halves after release are not compared (except the always
    inactive m1_n/halt_n/busak_n after release); from the second T state: floating buses, m1/halt/busak = 1."""
    out = [dont_care() for _ in range(2)]
    for _ in range(E0 + 2, E):
        out.append(dict(a=None, d_out=None, m1=1, mreq=None, iorq=None, rd=None, wr=None, rfsh=None, halt=1, busak=1,
                        bus_oe=0, d_oe=0))
    out += [dont_care(halt=1, m1=1, busak=1) for _ in range(2)]
    return out


# ------------------------------------------------------------------------------------- the scheduler
class Run:
    """Lays out cycles on the half-T timeline for a program + stimulus plan. `plan(n, c, h0, stim, run)` may add input events
    (including reset) for halves >= h0 before M cycle number n starts at h0; `txplan(e, j, stim)` before the j-th Tx at rising
    edge e. `run.pass_no` counts the resets seen so far. `vec` = the byte on the bus in INTA (int, or list: one per INTA)."""

    def __init__(self, mem, banks, stim, plan=None, txplan=None, vec=INTVEC):
        self.mem = bytearray(mem)
        self.banks = banks
        self.stim = stim
        self.plan = plan or (lambda *a: None)
        self.txplan = txplan or (lambda *a: None)
        self.rows = []
        self.cpu = Mini(self.mem)
        self.steps = []          # ('step', name, T, pc_after, i, r, cycles, response, info) or ('reset', bank)
        self.n = 0
        self.halt = 1
        self.pass_no = -1        # power-up reset makes it 0; each later reset adds 1
        self.queue = []          # remaining cycles of the current instruction
        self.cur = None
        self.resp = None         # 'NMI' / 'INT': accepted at the last instruction end, runs as the next "instruction"
        self.done_pairs = 0
        self.last_TH = 0
        self.vecs = vec if isinstance(vec, list) else [vec]
        self.n_inta = 0
        self.vec_ranges = []     # (first half, last half + 1, byte on the bus) per INTA
        self.nmi_pend, self.nmi_scan = False, 0
        self.dec = (False, False)       # (NMI pending, INT low) seen by the sample at the end of the current instruction, BUSRQ low = both False
        self.samp_prev = (False, False)
        self.halts = 0

    def S(self, sig, h):
        return self.stim.S(sig, max(h, -1))

    def pairs(self):
        """Reset intervals [E0, E) from the stimulus (E0 = first half with reset_n = 0)."""
        out, start = [], None
        for h, v in self.stim.ev["reset"]:
            h = max(h, 0)
            if v == 0 and start is None:
                start = h
            elif v == 1 and start is not None:
                out.append((start, h)); start = None
        return out            # an interval still open is not listed yet

    def run(self, done):
        """Extend the trace until done(self) is true (checked at cycle boundaries and after each reset)."""
        while True:
            p = self.pairs()
            if self.done_pairs < len(p) and (p[self.done_pairs][0] <= len(self.rows)):
                E0, E = p[self.done_pairs]
                assert E - E0 >= 6 and E0 % 2 == 0 and E % 2 == 0, f"reset [{E0},{E}) violates §5 item 4"
                del self.rows[E0:]                            # the abort: nothing from E0 on is a normal cycle
                self.rows += reset_rows(E0, E)
                bank = dict(self.stim.banks).get(E)
                if bank is not None:
                    for addr, data in self.banks[bank]:
                        self.mem[addr:addr + len(data)] = data
                self.steps.append(("reset", bank))
                self.cpu.reset()
                self.halt = 1
                self.resp = None
                self.nmi_pend, self.nmi_scan = False, len(self.rows)
                self.dec = self.samp_prev = (False, False)
                self.queue, self.cur = [], None
                self.done_pairs += 1
                self.pass_no += 1
                continue
            if done(self):
                return self.rows
            assert self.done_pairs < len(p) or self.rows, "power-up reset missing"
            assert len(self.rows) < 20000, "trace did not finish"
            self.one_cycle()

    def one_cycle(self):
        assert len(self.rows) % 2 == 0, "cycle not aligned to a rising edge"
        if not self.queue:
            if self.cur is not None:
                self.finish_instruction()
            resp, self.resp = self.resp, None
            if resp == "NMI":
                name, cyc = self.cpu.nmi()
            elif resp == "INT":
                self.cpu.vec = self.vecs[min(self.n_inta, len(self.vecs) - 1)]
                self.n_inta += 1
                name, cyc = self.cpu.inta()
            else:
                name, cyc = self.cpu.step()
                self.halts += name == "HALT"
            self.cur = (name, cyc, resp)
            self.queue = list(cyc)
        c = self.queue.pop(0)
        self.m_cycle(c, last=not self.queue)

    def m_cycle(self, c, last):
        h0 = len(self.rows)
        self.plan(self.n, c, h0, self.stim, self)
        self.n += 1
        rows, lastTH, halt = cycle_rows(c, h0, self.S, self.halt)
        self.last_TH = h0 + lastTH
        # BUSRQ sampled at the edge starting the last T state (§8.4 item 4, §4.4)
        self.busrq_at_end = self.S("busrq", self.last_TH - 1) == 0
        if last and self.cur[2] is None:
            self.dec = self.sample()
        if c.get("halt") and last and self.resp:
            rows, lastTH, halt = cycle_rows(c, h0, self.S, self.halt, accept=True)
        self.halt = halt
        self.rows += rows
        if c["k"] == "INTA":
            self.vec_ranges.append((h0, len(self.rows), c["data"]))
        if self.busrq_at_end:
            e, j = len(self.rows), 0
            while True:
                self.txplan(e, j, self.stim)
                self.rows.append(tx_row(self.halt))
                rel = self.S("busrq", e - 1) == 1
                r = tx_row(self.halt)
                if rel:
                    r["busak"] = 1
                self.rows.append(r)
                e += 2
                j += 1
                if rel:
                    break

    def sample(self):
        """INT and NMI at the edge P starting the last T state of an instruction (§8.4 item 4): BUSRQ low at P blocks both. NMI: a falling edge
        of nmi_n becomes pending at the edge where it is sampled 0 after 1 (item 6 rule 1), and P sees what became pending at an edge before P.
        NMI beats INT; INT needs IFF1 and not the end of EI (§8.1, item 5). Sets self.resp. Returns (NMI pending, INT low) for the ref."""
        c, P = self.cpu, self.last_TH
        for e in range(self.nmi_scan, P):
            if self.S("nmi", e - 1) == 0 and self.S("nmi", e - 2) == 1:
                self.nmi_pend = True
        self.nmi_scan = max(self.nmi_scan, P)
        blocked = c.ei_cnt > 0
        c.ei_cnt = 0
        if self.busrq_at_end:
            return (False, False)
        int_low = self.S("int", P - 1) == 0
        res = (self.nmi_pend, int_low)
        if self.nmi_pend:
            self.nmi_pend = False
            self.resp = "NMI"
        elif int_low and c.iff1 and not blocked:
            self.resp = "INT"
        return res

    def finish_instruction(self):
        """Closes the step: records the state the ref model is compared against (after the instruction, before any response it triggers)."""
        name, cyc, resp = self.cur
        c = self.cpu
        info = dict(samp=self.samp_prev, iff1=c.iff1, iff2=c.iff2, im=c.im, pv=c.pv, halted=c.halted)
        self.steps.append(("step", name, sum(x["T"] for x in cyc), c.pc, c.i, c.r, cyc, resp, info))
        self.cur = None
        self.samp_prev = (False, False) if resp else self.dec
