#!/usr/bin/env python3
"""Zilog Z80 instruction-level reference model (Beru, chip-z80#2).

Written from the DRAFT spec only (TuriChips/turichips docs/z80/spec.md @ b871a30), never from the RTL.
Spec references in comments: §6.0 opcode set, §6.1 T states, §6.2 flags, §6.3 F5/F3, R and HALT,
§8.1-8.4 interrupts. Nothing here is normative until Sai signs the spec off.

step() runs ONE instruction, one interrupt sequence, or one halted M1, and returns its T states.
Block repeats (LDIR ...) are one step per iteration (§8.4 item 5).

Not modelled (out of scope for this issue): per-M-cycle bus types and pin timing (open decision 7),
WAIT, BUSRQ, RESET timing. Only T-state totals per instruction (§6.1) are given.

Open decisions are switches in Policy, and only they (see README.md):
  Policy.x6   decision 6: S/Z after LDI/LDD(R), H after CPI/CPD(R), H after CCF
  Policy.daa  decision 8: DAA outside PM's 13-row table (and H after DAA)
Values: 'raise' (default: raise Unspecified at the instruction), 'taint' (no raise; the flag is marked
don't-care in cpu.fx and raising happens only if something consumes it), or the implemented choice
('mostek' for x6, 'nmos' for daa).

Flags Zilog marks X and that no decision covers (H after 16-bit adds, S and P/V after BIT, S/H/P/V after
block I/O) are always tainted in cpu.fx. F5/F3 are ordinary state (§6.3).

Usage: python3 ref/refz80.py   (prints the opcode-set census)
"""

S_, Z_, H_, PV_, N_, C_ = 0x80, 0x40, 0x10, 0x04, 0x02, 0x01
F53 = 0x28


class Undocumented(Exception):
    """An opcode form the 1977 manuals do not list (§1, §6.0): not specified, not tested."""


class Unspecified(Exception):
    """Behaviour the spec leaves open (decisions 6, 8, or an X flag was consumed)."""


class Policy:
    x6 = "raise"      # 'raise' | 'taint' | 'mostek'
    daa = "raise"     # 'raise' | 'taint' | 'nmos'

    def __init__(self, x6="raise", daa="raise"):
        assert x6 in ("raise", "taint", "mostek") and daa in ("raise", "taint", "nmos")
        self.x6, self.daa = x6, daa


PARITY = [1 if bin(i).count("1") % 2 == 0 else 0 for i in range(256)]


def s8(v):
    return v - 256 if v & 0x80 else v


class Z80:
    def __init__(self, policy=None, mem=None):
        self.policy = policy or Policy()
        self.mem = mem if mem is not None else bytearray(65536)
        self.io_in = lambda port: 0xFF
        self.io_out = lambda port, v: None
        self.int_data = lambda: 0xFF          # byte put on the bus in INTA: mode 0 opcode (RST only) or mode 2 vector
        self.reset()

    # ---- state -------------------------------------------------------------------------------------
    def reset(self):
        """§5: only PC, I, R, IFF1/2, IM are reset; other registers keep their values (init to 0 here)."""
        if not hasattr(self, "reg"):
            self.reg = [0] * 8                 # B C D E H L (6 unused) A
            self.alt = [0] * 8
            self.f = self.f2 = 0
            self.fx = self.fx2 = 0
            self.ix = self.iy = self.sp = 0
        self.pc = 0
        self.i = self.r = 0
        self.iff1 = self.iff2 = 0
        self.im = 0
        self.halted = False
        self.ei_delay = False
        self.nmi_pending = False
        self.int_line = False
        self.last = ""

    a = property(lambda s: s.reg[7], lambda s, v: s.reg.__setitem__(7, v & 255))

    def nmi(self):
        """A falling edge on nmi_n (§8.4 item 6): pending until the next sampling point."""
        self.nmi_pending = True

    # pairs: 0 BC 1 DE 2 HL 3 SP / AF
    def get_rp(self, p):
        if p == 3:
            return self.sp
        return self.reg[2 * p] << 8 | self.reg[2 * p + 1]

    def set_rp(self, p, v):
        v &= 0xFFFF
        if p == 3:
            self.sp = v
        else:
            self.reg[2 * p], self.reg[2 * p + 1] = v >> 8, v & 255

    @property
    def hl(self):
        return self.get_rp(2)

    @property
    def af(self):
        return self.a << 8 | self.f

    # ---- memory, I/O, fetch --------------------------------------------------------------------------
    def rd(self, a):
        return self.mem[a & 0xFFFF]

    def wr(self, a, v):
        self.mem[a & 0xFFFF] = v & 255

    def rd16(self, a):
        return self.rd(a) | self.rd(a + 1) << 8

    def wr16(self, a, v):
        self.wr(a, v & 255)
        self.wr(a + 1, v >> 8)

    def fetch(self):
        v = self.mem[self.pc]
        self.pc = (self.pc + 1) & 0xFFFF
        return v

    def fetch16(self):
        lo = self.fetch()
        return lo | self.fetch() << 8

    def m1(self):
        """§6.3 R rule 1: R[6:0]++ at the end of every M1, R[7] unchanged."""
        self.r = (self.r & 0x80) | ((self.r + 1) & 0x7F)

    def push(self, v):
        self.sp = (self.sp - 1) & 0xFFFF
        self.wr(self.sp, v >> 8)
        self.sp = (self.sp - 1) & 0xFFFF
        self.wr(self.sp, v & 255)

    def pop(self):
        lo = self.rd(self.sp)
        hi = self.rd(self.sp + 1)
        self.sp = (self.sp + 2) & 0xFFFF
        return lo | hi << 8

    # ---- flags ---------------------------------------------------------------------------------------
    def setf(self, written, value, x=0):
        """Any flag-writing instruction (a Table 6.0-1 row) clears F5/F3 (§6.3 rule 1). `written`: the
        flags the row changes; `x`: of those, the ones that are don't-care."""
        w = written | F53
        self.f = (self.f & ~w & 255) | (value & written)
        self.fx = (self.fx & ~w & 255) | (x & written)

    def need(self, mask, what):
        if self.fx & mask:
            raise Unspecified(f"{what} consumes flag(s) {self.fx & mask:#04x} left unspecified")

    def x6(self, flags, what):
        """Decision 6: returns the don't-care mask for `flags`, or raises."""
        if self.policy.x6 == "raise":
            raise Unspecified(f"decision 6: {what}")
        return flags if self.policy.x6 == "taint" else 0

    # ---- ALU -----------------------------------------------------------------------------------------
    def alu(self, op, v):
        """op: 0 ADD 1 ADC 2 SUB 3 SBC 4 AND 5 XOR 6 OR 7 CP, on A. §6.2 rows."""
        a = self.a
        if op in (0, 1, 2, 3, 7):
            c = 0
            if op in (1, 3):
                self.need(C_, "ADC/SBC")
                c = self.f & C_
            if op in (0, 1):
                r = a + v + c
                h = ((a & 15) + (v & 15) + c) > 15
                pv = ((a ^ r) & (v ^ r) & 0x80) != 0
                n, cy = 0, r > 255
            else:
                r = a - v - c
                h = ((a & 15) - (v & 15) - c) < 0
                pv = ((a ^ v) & (a ^ r) & 0x80) != 0
                n, cy = N_, r < 0
            r &= 255
            fl = (S_ if r & 0x80 else 0) | (Z_ if r == 0 else 0) | (H_ if h else 0) | (PV_ if pv else 0) | n | (C_ if cy else 0)
            self.setf(0xFF, fl)
            if op != 7:
                self.a = r
        else:
            r = (a & v) if op == 4 else (a ^ v) if op == 5 else (a | v)
            fl = (S_ if r & 0x80 else 0) | (Z_ if r == 0 else 0) | (H_ if op == 4 else 0) | (PV_ if PARITY[r] else 0)
            self.setf(0xFF, fl)
            self.a = r

    def incdec8(self, v, dec):
        r = (v - 1 if dec else v + 1) & 255
        h = (v & 15) == (0 if dec else 15)
        pv = v == (0x80 if dec else 0x7F)
        fl = (S_ if r & 0x80 else 0) | (Z_ if r == 0 else 0) | (H_ if h else 0) | (PV_ if pv else 0) | (N_ if dec else 0)
        self.setf(S_ | Z_ | H_ | PV_ | N_, fl)
        return r

    def rot(self, kind, v):
        """CB-group rotate/shift. kind 0 RLC 1 RRC 2 RL 3 RR 4 SLA 5 SRA 7 SRL (6 = SLL undocumented)."""
        if kind in (2, 3):
            self.need(C_, "RL/RR")
        c = self.f & C_
        if kind == 0:
            co = v >> 7; r = (v << 1 | co) & 255
        elif kind == 1:
            co = v & 1; r = (v >> 1 | co << 7) & 255
        elif kind == 2:
            co = v >> 7; r = (v << 1 | c) & 255
        elif kind == 3:
            co = v & 1; r = (v >> 1 | c << 7) & 255
        elif kind == 4:
            co = v >> 7; r = (v << 1) & 255
        elif kind == 5:
            co = v & 1; r = (v >> 1 | v & 0x80) & 255
        elif kind == 7:
            co = v & 1; r = v >> 1
        else:
            raise Undocumented("SLL")
        self.setf(0xFF, (S_ if r & 0x80 else 0) | (Z_ if r == 0 else 0) | (PV_ if PARITY[r] else 0) | (C_ if co else 0))
        return r

    def add16(self, a, b, c=0):
        r = a + b + c
        h = ((a & 0xFFF) + (b & 0xFFF) + c) > 0xFFF
        return r & 0xFFFF, h, r > 0xFFFF, ((a ^ r) & (b ^ r) & 0x8000) != 0

    def daa(self):
        """§6.2 DAA table (13 rows); outside it, and H, are open decision 8."""
        self.need(C_ | H_ | N_, "DAA")
        a, c, h, n = self.a, self.f & C_, bool(self.f & H_), bool(self.f & N_)
        hi, lo = a >> 4, a & 15
        add = None
        if not n:
            rows = [(0, range(0, 10), 0, range(0, 10), 0x00, 0), (0, range(0, 9), 0, range(10, 16), 0x06, 0),
                    (0, range(0, 10), 1, range(0, 4), 0x06, 0), (0, range(10, 16), 0, range(0, 10), 0x60, 1),
                    (0, range(9, 16), 0, range(10, 16), 0x66, 1), (0, range(10, 16), 1, range(0, 4), 0x66, 1),
                    (1, range(0, 3), 0, range(0, 10), 0x60, 1), (1, range(0, 3), 0, range(10, 16), 0x66, 1),
                    (1, range(0, 4), 1, range(0, 4), 0x66, 1)]
        else:
            rows = [(0, range(0, 10), 0, range(0, 10), 0x00, 0), (0, range(0, 9), 1, range(6, 16), 0xFA, 0),
                    (1, range(7, 16), 0, range(0, 10), 0xA0, 1), (1, range(6, 16), 1, range(6, 16), 0x9A, 1)]
        for rc, rh, rhf, rl, ad, co in rows:
            if c == rc and hi in rh and int(h) == rhf and lo in rl:
                add, cout = ad, co
                break
        if add is None:
            if self.policy.daa == "raise":
                raise Unspecified(f"decision 8: DAA outside the 13-row table (A={a:02X} C={c} H={int(h)} N={int(n)})")
            if self.policy.daa == "nmos":       # Sean Young's algorithm, as proposed by the spec's option (a); NOT chosen yet
                add = (6 if (h or lo > 9) else 0) | (0x60 if (c or a > 0x99) else 0)
                cout = 1 if (c or a > 0x99) else 0
                if n:
                    add = -add & 255
            else:                               # taint: result of A and C unknown too, use NMOS value, mark all
                add = (6 if (h or lo > 9) else 0) | (0x60 if (c or a > 0x99) else 0)
                cout = 1 if (c or a > 0x99) else 0
                if n:
                    add = -add & 255
        r = (a + add) & 255
        # NMOS rule for H (not in the manuals): only used under 'nmos'/'taint'.
        hn = ((lo > 9) if not n else (h and lo < 6))
        if self.policy.daa == "nmos":
            hx = 0
        elif self.policy.daa == "taint":
            hx = H_
        else:
            hx = H_                              # H after DAA is never defined, even inside the table (§6.2)
        self.setf(S_ | Z_ | H_ | PV_ | C_, (S_ if r & 0x80 else 0) | (Z_ if r == 0 else 0) | (H_ if hn else 0) | (PV_ if PARITY[r] else 0) | (C_ if cout else 0), hx)
        self.a = r

    # ---- conditions ----------------------------------------------------------------------------------
    def cond(self, cc):
        mask = (Z_, Z_, C_, C_, PV_, PV_, S_, S_)[cc]
        self.need(mask, "conditional")
        flag = bool(self.f & mask)
        return flag if cc & 1 else not flag

    # ---- 8-bit register access by code (6 = (HL) or (IX+d)) --------------------------------------
    def getr(self, code, ea=None):
        if code == 6:
            return self.rd(self.hl if ea is None else ea)
        return self.reg[code]

    def setr(self, code, v, ea=None):
        if code == 6:
            self.wr(self.hl if ea is None else ea, v)
        else:
            self.reg[code] = v & 255

    # ---- step ----------------------------------------------------------------------------------------
    def step(self):
        """Run one instruction / interrupt sequence / halted M1. Returns T states (§6.1, §8.2)."""
        blocked = self.ei_delay
        self.ei_delay = False
        if self.nmi_pending:                     # §8.2: 11 T = OCF(5) SWH SWL; PC not advanced, IFF2 keeps IFF1
            self.nmi_pending = False
            self.halted = False
            self.m1()
            self.iff1 = 0
            self.push(self.pc)
            self.pc = 0x66
            self.last = "NMI"
            return 11
        if self.int_line and self.iff1 and not blocked:
            self.halted = False
            self.iff1 = self.iff2 = 0
            self.m1()
            if self.im == 1:                     # §8.2: INTA(7) SWH SWL = 13
                self.push(self.pc)
                self.pc = 0x38
                self.last = "INT1"
                return 13
            if self.im == 2:                     # INTA(7) SWH SWL MRL MRH = 19
                vec = self.int_data() & 255
                if vec & 1:
                    raise Unspecified("mode 2 vector with bit 0 = 1 (§8.2)")
                self.push(self.pc)
                self.pc = self.rd16(self.i << 8 | vec)
                self.last = f"INT2 {vec:02X}"
                return 19
            op = self.int_data() & 255           # mode 0: RST p only (§8.2), INTA(6) SWH SWL = 12
            if op & 0xC7 != 0xC7:
                raise Unspecified(f"mode 0 with non-RST byte {op:02X} (§8.2)")
            self.push(self.pc)
            self.pc = op & 0x38
            self.last = f"INT0 RST {op & 0x38:02X}"
            return 12
        if self.halted:                          # §4.7/§6.3: NOP forced, PC stays at HALT+1, R++
            self.m1()
            self.last = "HALT-M1"
            return 4
        start = self.pc
        t = self.execute()
        self.last = " ".join(f"{self.mem[(start + k) & 0xFFFF]:02X}" for k in range((self.pc - start) & 0xFFFF))
        return t

    # ---- the instruction set -----------------------------------------------------------------------------
    def execute(self):
        self.m1()
        op = self.fetch()
        if op == 0xCB:
            self.m1()
            return self.cb(self.fetch())
        if op == 0xED:
            self.m1()
            return self.ed(self.fetch())
        if op in (0xDD, 0xFD):
            self.m1()
            return self.indexed(op)
        return self.main(op)

    def main(self, op):
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        p, q = y >> 1, y & 1
        if x == 1:
            if op == 0x76:
                self.halted = True
                return 4
            if y == 6:
                self.wr(self.hl, self.reg[z]); return 7
            if z == 6:
                self.reg[y] = self.rd(self.hl); return 7
            self.reg[y] = self.reg[z]
            return 4
        if x == 2:
            self.alu(y, self.getr(z))
            return 7 if z == 6 else 4
        if x == 0:
            if z == 0:
                if y == 0: return 4
                if y == 1:
                    self.reg[7], self.alt[7] = self.alt[7], self.reg[7]
                    self.f, self.f2 = self.f2, self.f
                    self.fx, self.fx2 = self.fx2, self.fx
                    return 4
                e = s8(self.fetch())
                if y == 2:                            # DJNZ
                    self.reg[0] = (self.reg[0] - 1) & 255
                    if self.reg[0]:
                        self.pc = (self.pc + e) & 0xFFFF; return 13
                    return 8
                if y == 3:
                    self.pc = (self.pc + e) & 0xFFFF; return 12
                if self.cond(y - 4):
                    self.pc = (self.pc + e) & 0xFFFF; return 12
                return 7
            if z == 1:
                if q == 0:
                    self.set_rp(p, self.fetch16()); return 10
                r, h, c, _ = self.add16(self.hl, self.get_rp(p))
                self.set_rp(2, r)
                self.setf(H_ | N_ | C_, (C_ if c else 0), H_)
                return 11
            if z == 2:
                if y == 0: self.wr(self.get_rp(0), self.a); return 7
                if y == 1: self.a = self.rd(self.get_rp(0)); return 7
                if y == 2: self.wr(self.get_rp(1), self.a); return 7
                if y == 3: self.a = self.rd(self.get_rp(1)); return 7
                nn = self.fetch16()
                if y == 4: self.wr16(nn, self.hl); return 16
                if y == 5: self.set_rp(2, self.rd16(nn)); return 16
                if y == 6: self.wr(nn, self.a); return 13
                self.a = self.rd(nn); return 13
            if z == 3:
                self.set_rp(p, self.get_rp(p) + (-1 if q else 1))
                return 6
            if z == 4:
                self.setr(y, self.incdec8(self.getr(y), 0)); return 11 if y == 6 else 4
            if z == 5:
                self.setr(y, self.incdec8(self.getr(y), 1)); return 11 if y == 6 else 4
            if z == 6:
                n = self.fetch()
                self.setr(y, n); return 10 if y == 6 else 7
            return self.acc_misc(y)
        # x == 3
        if z == 0:
            if self.cond(y):
                self.pc = self.pop(); return 11
            return 5
        if z == 1:
            if q == 0:
                v = self.pop()
                if p == 3:
                    self.a, self.f, self.fx = v >> 8, v & 255, 0
                else:
                    self.set_rp(p, v)
                return 10
            if p == 0: self.pc = self.pop(); return 10
            if p == 1:
                self.reg[0:6], self.alt[0:6] = self.alt[0:6], self.reg[0:6]; return 4
            if p == 2: self.pc = self.hl; return 4
            self.sp = self.hl; return 6
        if z == 2:
            nn = self.fetch16()
            if self.cond(y):
                self.pc = nn
            return 10
        if z == 3:
            if y == 0: self.pc = self.fetch16(); return 10
            if y == 2:
                n = self.fetch(); self.io_out(self.a << 8 | n, self.a); return 11
            if y == 3:
                n = self.fetch(); self.a = self.io_in(self.a << 8 | n) & 255; return 11
            if y == 4:
                lo = self.rd16(self.sp)
                self.wr16(self.sp, self.hl); self.set_rp(2, lo); return 19
            if y == 5:
                de, hl = self.get_rp(1), self.hl
                self.set_rp(1, hl); self.set_rp(2, de); return 4
            if y == 6: self.iff1 = self.iff2 = 0; return 4
            self.iff1 = self.iff2 = 1                    # EI (§8.1, §8.4: delay)
            self.ei_delay = True
            return 4
        if z == 4:
            nn = self.fetch16()
            if self.cond(y):
                self.push(self.pc); self.pc = nn; return 17
            return 10
        if z == 5:
            if q == 0:
                if p == 3:
                    self.need(0xFF, "PUSH AF"); self.push(self.af)
                else:
                    self.push(self.get_rp(p))
                return 11
            if p == 0:
                nn = self.fetch16(); self.push(self.pc); self.pc = nn; return 17
            raise Undocumented(f"{op:02X}")              # DD ED FD prefixes handled by caller
        if z == 6:
            self.alu(y, self.fetch()); return 7
        self.push(self.pc)
        self.pc = y * 8
        return 11

    def acc_misc(self, y):
        """Opcodes 07 0F 17 1F 27 2F 37 3F (z = 7)."""
        a = self.a
        if y < 4:                                         # RLCA RRCA RLA RRA
            if y == 2 or y == 3:
                self.need(C_, "RLA/RRA")
            c = self.f & C_
            if y == 0: co = a >> 7; r = (a << 1 | co) & 255
            elif y == 1: co = a & 1; r = (a >> 1 | co << 7) & 255
            elif y == 2: co = a >> 7; r = (a << 1 | c) & 255
            else: co = a & 1; r = (a >> 1 | c << 7) & 255
            self.a = r
            self.setf(H_ | N_ | C_, C_ if co else 0)
        elif y == 4:
            self.daa()
        elif y == 5:
            self.a = ~a & 255
            self.setf(H_ | N_, H_ | N_)
        elif y == 6:                                      # SCF
            self.setf(H_ | N_ | C_, C_)
        else:                                             # CCF
            self.need(C_, "CCF")
            c = self.f & C_
            if self.policy.x6 == "mostek":
                self.setf(H_ | N_ | C_, (H_ if c else 0) | (0 if c else C_))
            else:
                x = self.x6(H_, "H after CCF")
                self.setf(H_ | N_ | C_, (0 if c else C_), x)
        return 4

    # ---- CB ------------------------------------------------------------------------------------------
    def cb(self, op, ea=None):
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        mem = z == 6
        if x == 0:
            if y == 6:
                raise Undocumented(f"CB {op:02X} SLL")
            self.setr(z, self.rot(y, self.getr(z, ea)), ea)
            return (23 if ea is not None else 15) if mem else 8
        v = self.getr(z, ea)
        if x == 1:                                        # BIT: Z from bit, H=1, N=0, S and P/V are X
            zf = not (v >> y) & 1
            self.setf(S_ | Z_ | H_ | PV_ | N_, (Z_ if zf else 0) | H_ | (PV_ if zf else 0), S_ | PV_)
            return (20 if ea is not None else 12) if mem else 8
        v = (v & ~(1 << y)) if x == 2 else (v | 1 << y)
        self.setr(z, v, ea)
        return (23 if ea is not None else 15) if mem else 8

    # ---- DD / FD ---------------------------------------------------------------------------------------
    def indexed(self, pre):
        name = "ix" if pre == 0xDD else "iy"
        get = lambda: getattr(self, name)
        put = lambda v: setattr(self, name, v & 0xFFFF)
        op = self.fetch()
        if op == 0xCB:                                    # execute() already counted DD and this CB
            d = s8(self.fetch())
            op2 = self.fetch()                            # an OD, not an M1 (§6.3 R rule 1)
            if op2 & 7 != 6 or (op2 & 0xC0) == 0 and (op2 >> 3) & 7 == 6:
                raise Undocumented(f"{pre:02X} CB d {op2:02X}")
            return self.cb(op2, (get() + d) & 0xFFFF)
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        p, q = y >> 1, y & 1
        # (IX+d) memory operand forms
        if op in (0x34, 0x35, 0x36) or (x == 2 and z == 6) or (x == 1 and (y == 6) != (z == 6)):
            d = s8(self.fetch())
            ea = (get() + d) & 0xFFFF
            if op == 0x34: self.wr(ea, self.incdec8(self.rd(ea), 0)); return 23
            if op == 0x35: self.wr(ea, self.incdec8(self.rd(ea), 1)); return 23
            if op == 0x36: self.wr(ea, self.fetch()); return 19
            if x == 2:
                self.alu(y, self.rd(ea)); return 19
            if z == 6: self.reg[y] = self.rd(ea); return 19
            self.wr(ea, self.reg[z]); return 19
        if x == 0 and z == 1 and q == 1:                  # ADD IX,pp
            other = get() if p == 2 else self.get_rp(p)
            r, h, c, _ = self.add16(get(), other)
            put(r)
            self.setf(H_ | N_ | C_, C_ if c else 0, H_)
            return 15
        if op == 0x21: put(self.fetch16()); return 14
        if op == 0x22: self.wr16(self.fetch16(), get()); return 20
        if op == 0x2A: put(self.rd16(self.fetch16())); return 20
        if op == 0x23: put(get() + 1); return 10
        if op == 0x2B: put(get() - 1); return 10
        if op == 0xE1: put(self.pop()); return 14
        if op == 0xE5: self.push(get()); return 15
        if op == 0xE3:
            lo = self.rd16(self.sp); self.wr16(self.sp, get()); put(lo); return 23
        if op == 0xE9: self.pc = get(); return 8
        if op == 0xF9: self.sp = get(); return 10
        raise Undocumented(f"{pre:02X} {op:02X}")

    # ---- ED --------------------------------------------------------------------------------------------
    def ed(self, op):
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        p, q = y >> 1, y & 1
        if x == 1:
            if z == 0 and y != 6:                         # IN r,(C)
                v = self.io_in(self.get_rp(0)) & 255
                self.reg[y] = v
                self.setf(S_ | Z_ | H_ | PV_ | N_, (S_ if v & 0x80 else 0) | (Z_ if v == 0 else 0) | (PV_ if PARITY[v] else 0))
                return 12
            if z == 1 and y != 6:                         # OUT (C),r
                self.io_out(self.get_rp(0), self.reg[y]); return 12
            if z == 2:
                a, b = self.hl, self.get_rp(p)
                if q == 0:                                # SBC HL,ss
                    self.need(C_, "SBC HL")
                    c = self.f & C_
                    r = a - b - c
                    h = ((a & 0xFFF) - (b & 0xFFF) - c) < 0
                    pv = ((a ^ b) & (a ^ r) & 0x8000) != 0
                    n, cy = N_, r < 0
                else:
                    self.need(C_, "ADC HL")
                    c = self.f & C_
                    r = a + b + c
                    h = ((a & 0xFFF) + (b & 0xFFF) + c) > 0xFFF
                    pv = ((a ^ r) & (b ^ r) & 0x8000) != 0
                    n, cy = 0, r > 0xFFFF
                r &= 0xFFFF
                self.set_rp(2, r)
                self.setf(0xFF & ~0x28, (S_ if r & 0x8000 else 0) | (Z_ if r == 0 else 0) | (H_ if h else 0) | (PV_ if pv else 0) | n | (C_ if cy else 0), H_)
                return 15
            if z == 3:
                nn = self.fetch16()
                if q == 0: self.wr16(nn, self.get_rp(p))
                else: self.set_rp(p, self.rd16(nn))
                return 20
            if z == 4 and y == 0:                         # NEG
                v = self.a
                self.a = 0
                self.alu(2, v)
                return 8
            if z == 5 and y in (0, 1):                    # RETN / RETI
                self.pc = self.pop()
                if y == 0:
                    self.iff1 = self.iff2                 # RETN (§8.1); RETI leaves IFF alone
                return 14
            if z == 6 and y in (0, 2, 3):
                self.im = (0, 0, 1, 2)[y]
                return 8
            if z == 7:
                if y in (0, 1, 2, 3):
                    if y == 0: self.i = self.a
                    elif y == 1:
                        self.r = self.a                   # at the end, after own increments (§6.3 R rule 3)
                    else:
                        v = self.i if y == 2 else self.r
                        self.a = v
                        self.setf(S_ | Z_ | H_ | PV_ | N_, (S_ if v & 0x80 else 0) | (Z_ if v == 0 else 0) | (PV_ if self.iff2 else 0))
                    return 9
                if y in (4, 5):                           # RRD / RLD
                    hl = self.hl
                    m = self.rd(hl)
                    a = self.a
                    if y == 5:                            # RLD
                        self.wr(hl, (m << 4 | a & 15) & 255)
                        self.a = a & 0xF0 | m >> 4
                    else:                                 # RRD
                        self.wr(hl, (a & 15) << 4 | m >> 4)
                        self.a = a & 0xF0 | m & 15
                    r = self.a
                    self.setf(S_ | Z_ | H_ | PV_ | N_, (S_ if r & 0x80 else 0) | (Z_ if r == 0 else 0) | (PV_ if PARITY[r] else 0))
                    return 18
        if x == 2 and z < 4 and y >= 4:
            return self.block(y, z)
        raise Undocumented(f"ED {op:02X}")

    def block(self, y, z):
        """y: 4 inc, 5 dec, 6 inc-repeat, 7 dec-repeat. z: 0 LD 1 CP 2 IN 3 OUT. §6.1, §6.2 rows."""
        dec = y & 1
        rep = y >= 6
        step = -1 if dec else 1
        hl = self.hl
        again = False
        if z == 0:                                        # LDI/LDD
            self.wr(self.get_rp(1), self.rd(hl))
            self.set_rp(1, self.get_rp(1) + step)
            self.set_rp(2, hl + step)
            bc = (self.get_rp(0) - 1) & 0xFFFF
            self.set_rp(0, bc)
            if self.policy.x6 == "mostek":                # "Not affected": S and Z stay as they were
                self.setf(H_ | PV_ | N_, PV_ if bc else 0)
            else:
                self.setf(S_ | Z_ | H_ | PV_ | N_, PV_ if bc else 0, self.x6(S_ | Z_, "S/Z after LDI/LDD"))
            again = rep and bc != 0
        elif z == 1:                                      # CPI/CPD
            m = self.rd(hl)
            a = self.a
            r = (a - m) & 255
            self.set_rp(2, hl + step)
            bc = (self.get_rp(0) - 1) & 0xFFFF
            self.set_rp(0, bc)
            h = ((a & 15) - (m & 15)) < 0
            fl = (S_ if r & 0x80 else 0) | (Z_ if r == 0 else 0) | (PV_ if bc else 0) | N_
            if self.policy.x6 == "mostek":
                fl |= H_ if h else 0
                x = 0
            else:
                x = self.x6(H_, "H after CPI/CPD")
                fl |= H_ if h else 0
            self.setf(S_ | Z_ | H_ | PV_ | N_, fl, x)
            again = rep and bc != 0 and r != 0
        elif z == 2:                                      # INI/IND: port address {B before dec, C}
            v = self.io_in(self.get_rp(0)) & 255
            self.wr(hl, v)
            self.set_rp(2, hl + step)
            self.reg[0] = (self.reg[0] - 1) & 255
            self.setf(S_ | Z_ | H_ | PV_ | N_, (Z_ if self.reg[0] == 0 else 0) | N_, S_ | H_ | PV_)
            again = rep and self.reg[0] != 0
        else:                                             # OUTI/OUTD: B decremented first, port {B-1, C}
            v = self.rd(hl)
            self.reg[0] = (self.reg[0] - 1) & 255
            self.io_out(self.get_rp(0), v)
            self.set_rp(2, hl + step)
            self.setf(S_ | Z_ | H_ | PV_ | N_, (Z_ if self.reg[0] == 0 else 0) | N_, S_ | H_ | PV_)
            again = rep and self.reg[0] != 0
        if again:
            self.pc = (self.pc - 2) & 0xFFFF
            return 21
        return 16


# ---- opcode-set census (§6.0): which forms does this model execute? -----------------------------------
def census():
    """Probe every opcode form on a scratch CPU. Returns (documented forms, per-group counts).
    A form counts if executing it doesn't raise Undocumented. Policy 'taint' keeps decision cases quiet."""
    groups = {"main": 0, "CB": 0, "DD": 0, "ED": 0, "FD": 0}
    forms = set()
    for pre, rng in (("main", range(256)), ("CB", range(256)), ("ED", range(256))):
        for op in rng:
            if pre == "main" and op in (0xCB, 0xDD, 0xED, 0xFD):
                continue
            c = Z80(Policy("taint", "taint"))
            c.pc = 0x100
            c.sp = 0x8000
            seq = {"main": [op], "CB": [0xCB, op], "ED": [0xED, op]}[pre]
            c.mem[0x100:0x100 + len(seq)] = bytes(seq + [0, 0, 0])
            try:
                c.step()
            except Undocumented:
                continue
            except Unspecified:
                pass
            groups[pre] += 1
            forms.add((pre, op))
    for pre, name in ((0xDD, "DD"), (0xFD, "FD")):
        for op in range(256):
            if op in (0xCB, 0xDD, 0xED, 0xFD):
                continue
            c = Z80(Policy("taint", "taint"))
            c.pc = 0x100
            c.sp = 0x8000
            c.mem[0x100:0x104] = bytes([pre, op, 0, 0])
            try:
                c.step()
            except Undocumented:
                continue
            except Unspecified:
                pass
            groups[name] += 1
            forms.add((name, op))
        for op in range(256):
            c = Z80(Policy("taint", "taint"))
            c.pc = 0x100
            c.mem[0x100:0x104] = bytes([pre, 0xCB, 0, op])
            try:
                c.step()
            except Undocumented:
                continue
            except Unspecified:
                pass
            groups[name] += 1
            forms.add((name, "CB", op))
    return forms, groups


if __name__ == "__main__":
    forms, groups = census()
    print(groups, "total", len(forms))
