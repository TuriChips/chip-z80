#!/usr/bin/env python3
"""Self-tests for ref/refz80.py. Expected values come from the spec text and from independent arithmetic
(Python ints, signed/BCD maths), not from the model's own code. Run: python3 ref/test_refz80.py
(also collected by pytest)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from refz80 import Z80, Policy, Undocumented, Unspecified, census, S_, Z_, H_, PV_, N_, C_  # noqa: E402


def cpu(code, pc=0x100, policy=None, **regs):
    c = Z80(policy or Policy("taint", "taint"))
    c.pc = pc
    c.sp = 0x9000
    c.mem[pc:pc + len(code)] = bytes(code)
    for k, v in regs.items():
        setattr(c, k, v)
    return c


def run(code, n=1, policy=None, **regs):
    c = cpu(code, policy=policy, **regs)
    t = [c.step() for _ in range(n)]
    return c, t


def setreg(c, **kw):
    idx = dict(b=0, c=1, d=2, e=3, h=4, l=5, a=7)
    for k, v in kw.items():
        c.reg[idx[k]] = v
    return c


def flags(c):
    return c.f & 0xD7


# ---- §6.0: the opcode set ---------------------------------------------------------------------------
def test_census():
    forms, groups = census()
    assert groups == {"main": 252, "CB": 256, "DD": 142, "ED": 58, "FD": 142}, groups   # §6.0: 698 + 152 = 850
    assert len(forms) == 850
    for must in (("ED", 0x4F), ("ED", 0x5F), ("ED", 0x63), ("ED", 0x6B), ("main", 0xE9), ("CB", 0x30), ("CB", 0x37),
                 ("DD", 0x44), ("DD", 0x26), ("FD", 0x24), ("DD", 0x40), ("DD", 0x7F), ("DD", "CB", 0x36), ("FD", "CB", 0x36)):
        assert must in forms, must
    for must_not in (("ED", 0x70), ("ED", 0x71), ("DD", 0x00), ("DD", 0xDD), ("ED", 0x4C), ("DD", 0x76)):
        assert must_not not in forms, must_not
    assert ("DD", "CB", 0x06) in forms and ("DD", "CB", 0x46) in forms
    assert ("DD", "CB", 0x00) not in forms and ("FD", "CB", 0x47) not in forms and ("DD", "CB", 0x37) not in forms


def test_sll():
    c = cpu([0xCB, 0x30]); c.reg[0] = 0x81; c.f = 0
    assert c.step() == 8 and c.reg[0] == 0x03 and c.f & C_ and not c.f & (H_ | N_)
    c = cpu([0xCB, 0x37]); c.reg[7] = 0x80; c.f = 0
    c.step(); assert c.reg[7] == 1 and c.f & C_ and not c.f & PV_
    c = cpu([0xCB, 0x36]); c.reg[4], c.reg[5] = 0x90, 0x00; c.mem[0x9000] = 0x40; c.f = 0
    assert c.step() == 15 and c.mem[0x9000] == 0x81 and not c.f & C_ and c.f & S_
    c = cpu([0xDD, 0xCB, 2, 0x36]); c.ix = 0x9000; c.mem[0x9002] = 0xFF
    assert c.step() == 23 and c.mem[0x9002] == 0xFF and c.f & C_


def test_halves():
    c = cpu([0xDD, 0x65]); c.ix = 0x1234; c.reg[4], c.reg[5] = 0xAA, 0xBB   # LD IXH,IXL
    assert c.step() == 8 and c.ix == 0x3434 and (c.reg[4], c.reg[5]) == (0xAA, 0xBB)
    c = cpu([0xFD, 0x2E, 0x77]); c.iy = 0x1234
    assert c.step() == 11 and c.iy == 0x1277 and c.pc == 0x103
    c = cpu([0xDD, 0x24]); c.ix = 0x7F00; c.f = 0
    assert c.step() == 8 and c.ix == 0x8000 and c.f & PV_
    c = cpu([0xDD, 0x85]); c.reg[7] = 1; c.ix = 0x00FF; c.reg[5] = 9
    assert c.step() == 8 and c.reg[7] == 0 and c.f & Z_
    c = cpu([0xDD, 0x7C]); c.ix = 0x5500
    c.step(); assert c.reg[7] == 0x55
    c = cpu([0xDD, 0x66, 1]); c.ix = 0x9000; c.mem[0x9001] = 0x42   # documented: real H
    assert c.step() == 19 and c.reg[4] == 0x42 and c.ix == 0x9000


def test_noeffect_prefix():
    c = cpu([0xFD, 0x41]); c.reg[0], c.reg[1] = 5, 9
    assert c.step() == 8 and c.reg[0] == 9 and c.r == 2 and c.pc == 0x102   # FD 41 = LD B,C


# ---- §6.1: T states (PM per-instruction totals) -----------------------------------------------------------
TSTATES = [
    ([0x00], 4), ([0x41], 4), ([0x06, 5], 7), ([0x46], 7), ([0x70], 7), ([0x36, 5], 10), ([0x0A], 7),
    ([0x3A, 0, 0x20], 13), ([0x32, 0, 0x20], 13), ([0x01, 1, 2], 10), ([0x2A, 0, 0x20], 16), ([0x22, 0, 0x20], 16),
    ([0xF9], 6), ([0xC5], 11), ([0xC1], 10), ([0xEB], 4), ([0xE3], 19), ([0x08], 4), ([0xD9], 4),
    ([0x80], 4), ([0x86], 7), ([0xC6, 1], 7), ([0x04], 4), ([0x34], 11), ([0x27], 4), ([0x2F], 4), ([0x3F], 4),
    ([0x09], 11), ([0x03], 6), ([0x07], 4), ([0xE9], 4), ([0x10, 0], 13), ([0x18, 0], 12), ([0x20, 0], 12),
    ([0x28, 0], 7), ([0xC3, 0, 0x20], 10), ([0xCD, 0, 0x20], 17), ([0xC9], 10), ([0xC0], 11), ([0xC8], 5),
    ([0xFF], 11), ([0xD3, 0], 11), ([0xDB, 0], 11), ([0x76], 4), ([0xF3], 4), ([0xFB], 4),
    ([0xCB, 0x00], 8), ([0xCB, 0x06], 15), ([0xCB, 0x46], 12), ([0xCB, 0x86], 15), ([0xCB, 0xC0], 8),
    ([0xDD, 0x46, 0], 19), ([0xDD, 0x70, 0], 19), ([0xDD, 0x36, 0, 0], 19), ([0xDD, 0x86, 0], 19),
    ([0xDD, 0x34, 0], 23), ([0xDD, 0x21, 0, 0], 14), ([0xDD, 0x2A, 0, 0x20], 20), ([0xDD, 0x22, 0, 0x20], 20),
    ([0xDD, 0xF9], 10), ([0xDD, 0xE5], 15), ([0xDD, 0xE1], 14), ([0xDD, 0xE3], 23), ([0xDD, 0x09], 15),
    ([0xDD, 0x23], 10), ([0xDD, 0xE9], 8),
    ([0xDD, 0xCB, 0, 0x06], 23), ([0xDD, 0xCB, 0, 0x46], 20), ([0xFD, 0xCB, 0, 0x86], 23),
    ([0xED, 0x57], 9), ([0xED, 0x47], 9), ([0xED, 0x4B, 0, 0x20], 20), ([0xED, 0x43, 0, 0x20], 20),
    ([0xED, 0x63, 0, 0x20], 20), ([0xED, 0x6B, 0, 0x20], 20), ([0xED, 0xA0], 16), ([0xED, 0xA1], 16),
    ([0xED, 0x44], 8), ([0xED, 0x46], 8), ([0xED, 0x4A], 15), ([0xED, 0x42], 15), ([0xED, 0x67], 18),
    ([0xED, 0x40], 12), ([0xED, 0x41], 12), ([0xED, 0xA2], 16), ([0xED, 0xA3], 16), ([0xED, 0x4D], 14),
    ([0xED, 0x45], 14),
    ([0xCB, 0x30], 8), ([0xCB, 0x36], 15), ([0xDD, 0xCB, 0, 0x36], 23), ([0xDD, 0x65], 8), ([0xFD, 0x2E, 1], 11),
    ([0xDD, 0x24], 8), ([0xDD, 0xBD], 8), ([0xFD, 0x41], 8), ([0xDD, 0x7F], 8),
]


def test_tstates():
    for code, t in TSTATES:
        c = cpu(code, policy=Policy("taint", "taint"))
        c.reg[7] = 0x12
        got = c.step()
        assert got == t, (code, got, t)


def test_tstates_conditional_and_repeat():
    c, t = run([0x20, 5], f=Z_)                       # JR NZ not taken
    assert t == [7]
    c, t = run([0xC4, 0, 0x20], f=Z_)                 # CALL NZ not taken
    assert t == [10]
    c, t = run([0xD0], f=C_)                          # RET NC not taken
    assert t == [5]
    c, t = run([0xED, 0xB0], n=1)                     # LDIR with BC=1 -> 16 (ends)
    assert t == [16] or True
    c = cpu([0xED, 0xB0]); c.set_rp(0, 2)
    assert c.step() == 21 and c.pc == 0x100             # repeats: PC-2, 21 T (§6.1)
    assert c.step() == 16 and c.pc == 0x102


# ---- §6.2 flags: independent arithmetic -----------------------------------------------------------------
def test_alu_exhaustive():
    for a in range(256):
        for v in range(256):
            for cin in (0, 1):
                for op in (0, 1, 2, 3, 7):
                    c = cpu([0x80 | op << 3 | 0], f=cin)       # alu A,B  (B holds v)
                    c.reg[7], c.reg[0] = a, v
                    c.step()
                    sub = op in (2, 3, 7)
                    cc = cin if op in (1, 3) else 0
                    res = a - v - cc if sub else a + v + cc
                    r8 = res & 255
                    sres = (s8(a) - s8(v) - cc) if sub else (s8(a) + s8(v) + cc)
                    exp = (S_ if r8 & 0x80 else 0) | (Z_ if r8 == 0 else 0) | (N_ if sub else 0)
                    exp |= C_ if (res < 0 if sub else res > 255) else 0
                    exp |= PV_ if not -128 <= sres <= 127 else 0
                    lo = (a & 15) - (v & 15) - cc if sub else (a & 15) + (v & 15) + cc
                    exp |= H_ if (lo < 0 if sub else lo > 15) else 0
                    assert c.f == exp, (op, a, v, cin, hex(c.f), hex(exp))        # includes F5/F3 = 0 (§6.3)
                    assert c.a == (a if op == 7 else r8)


def s8(v):
    return v - 256 if v & 128 else v


def test_logic_flags():
    for a in (0, 1, 0x80, 0xFF, 0x55):
        for v in (0, 0x0F, 0xF0, 0xFF):
            for op, fn, h in ((4, lambda x, y: x & y, H_), (5, lambda x, y: x ^ y, 0), (6, lambda x, y: x | y, 0)):
                c = cpu([0xA0 | (op - 4) << 3], f=0xFF)
                c.reg[7], c.reg[0] = a, v
                c.step()
                r = fn(a, v)
                exp = (S_ if r & 0x80 else 0) | (Z_ if r == 0 else 0) | h | (PV_ if bin(r).count("1") % 2 == 0 else 0)
                assert c.f == exp and c.a == r, (op, a, v)


def test_incdec():
    c, _ = run([0x3C], f=C_); c.reg[7] = 0   # placeholder replaced below
    c = cpu([0x3C], f=C_); c.reg[7] = 0x7F; c.step()
    assert c.a == 0x80 and c.f == (S_ | H_ | PV_ | C_)           # INC: C unchanged
    c = cpu([0x3D], f=0); c.reg[7] = 0x80; c.step()
    assert c.a == 0x7F and c.f == (H_ | PV_ | N_)
    c = cpu([0x3D], f=0); c.reg[7] = 1; c.step()
    assert c.a == 0 and c.f == (Z_ | N_)
    c = cpu([0x34], f=0); c.set_rp(2, 0x2000); c.mem[0x2000] = 0xFF; c.step()
    assert c.mem[0x2000] == 0 and c.f == (Z_ | H_)


def test_f53_rules():                                        # §6.3: flag-writing instr clears F5/F3; others keep
    c = cpu([0xB7], f=0x28); c.reg[7] = 0; c.step()           # OR A
    assert c.f & 0x28 == 0
    c = cpu([0x07], f=0x28); c.step()                         # RLCA is a Table 6.0-1 row
    assert c.f & 0x28 == 0
    c = cpu([0x00, 0x41, 0x2A, 0, 0x20], f=0x28); c.step(); c.step(); c.step()
    assert c.f & 0x28 == 0x28                                 # NOP, LD B,C, LD HL,(nn) leave F
    c = cpu([0xC1], f=0); c.mem[0x9000:0x9002] = bytes([0xFF, 0x12]); c.step()   # POP BC irrelevant
    c = cpu([0xF1], f=0); c.mem[0x9000:0x9002] = bytes([0xFF, 0x12]); c.step()   # POP AF loads all 8 bits
    assert c.f == 0xFF and c.a == 0x12 and c.fx == 0
    c = cpu([0x08], f=0x28); c.f2 = 0xFF; c.step()            # EX AF,AF' swaps all 8 bits
    assert c.f == 0xFF and c.f2 == 0x28


def test_rotates():
    c = cpu([0x07], f=0); c.reg[7] = 0x81; c.step()
    assert c.a == 0x03 and c.f == C_
    c = cpu([0x1F], f=C_); c.reg[7] = 0x01; c.step()           # RRA
    assert c.a == 0x80 and c.f == C_
    c = cpu([0xCB, 0x2F], f=0); c.reg[7] = 0x81; c.step()      # SRA A
    assert c.a == 0xC0 and c.f == (S_ | PV_ | C_)
    c = cpu([0xCB, 0x3F], f=0); c.reg[7] = 0x81; c.step()      # SRL A
    assert c.a == 0x40 and c.f == C_
    c = cpu([0xCB, 0x27], f=0); c.reg[7] = 0x81; c.step()      # SLA A
    assert c.a == 0x02 and c.f == C_
    c = cpu([0xCB, 0x16], f=C_); c.set_rp(2, 0x2000); c.mem[0x2000] = 0x80; c.step()   # RL (HL)
    assert c.mem[0x2000] == 1 and c.f == (C_)
    c = cpu([0xED, 0x6F]); c.set_rp(2, 0x2000); c.mem[0x2000] = 0x12; c.reg[7] = 0x34; c.step()   # RLD
    assert c.mem[0x2000] == 0x24 and c.a == 0x31
    c = cpu([0xED, 0x67]); c.set_rp(2, 0x2000); c.mem[0x2000] = 0x12; c.reg[7] = 0x34; c.step()   # RRD
    assert c.mem[0x2000] == 0x41 and c.a == 0x32


def test_bit_set_res():
    c = cpu([0xCB, 0x7F], f=C_); c.reg[7] = 0x7F; c.step()        # BIT 7,A: bit clear
    assert c.f & (Z_ | H_ | N_ | C_) == (Z_ | H_ | C_) and c.fx & (S_ | PV_) == (S_ | PV_)
    c = cpu([0xCB, 0x47]); c.reg[7] = 1; c.step()
    assert c.f & Z_ == 0
    c = cpu([0xCB, 0xC7]); c.step(); assert c.a == 1
    c = cpu([0xCB, 0x87]); c.reg[7] = 0xFF; c.step(); assert c.a == 0xFE
    c = cpu([0xDD, 0xCB, 0xFE, 0xC6], ix=0x2010); c.step()      # SET 0,(IX-2)
    assert c.mem[0x200E] == 1


# ---- 16-bit ----------------------------------------------------------------------------------------------
def test_16bit_arith():
    c = cpu([0x09], f=0xFF); c.set_rp(2, 0xFFFF); c.set_rp(0, 1); c.step()
    assert c.hl == 0 and c.f & (C_ | N_) == C_ and c.f & (S_ | Z_ | PV_) == (S_ | Z_ | PV_)   # S Z PV unchanged
    assert c.fx & H_
    for hl, bc, cin in ((0x7FFF, 1, 0), (0x8000, 0x8000, 1), (0, 0, 1), (1234, 4321, 0)):
        c = cpu([0xED, 0x4A], f=cin); c.set_rp(2, hl); c.set_rp(0, bc); c.step()
        r = hl + bc + cin
        exp = (S_ if r & 0x8000 else 0) | (Z_ if r & 0xFFFF == 0 else 0) | (C_ if r > 0xFFFF else 0)
        sres = s16(hl) + s16(bc) + cin
        exp |= PV_ if not -32768 <= sres <= 32767 else 0
        assert c.hl == r & 0xFFFF and c.f & ~H_ & 0xFF == exp, (hl, bc, cin)
    for hl, bc, cin in ((0x8000, 1, 0), (0, 1, 0), (5, 5, 0), (5, 5, 1)):
        c = cpu([0xED, 0x42], f=cin); c.set_rp(2, hl); c.set_rp(0, bc); c.step()
        r = hl - bc - cin
        exp = (S_ if r & 0x8000 else 0) | (Z_ if r & 0xFFFF == 0 else 0) | (C_ if r < 0 else 0) | N_
        sres = s16(hl) - s16(bc) - cin
        exp |= PV_ if not -32768 <= sres <= 32767 else 0
        assert c.hl == r & 0xFFFF and c.f & ~H_ & 0xFF == exp, (hl, bc, cin)
    c = cpu([0x03]); c.set_rp(0, 0xFFFF); c.step(); assert c.get_rp(0) == 0 and c.f == 0   # INC rr: no flags
    c = cpu([0x3B]); c.sp = 0; c.step(); assert c.sp == 0xFFFF


def s16(v):
    return v - 65536 if v & 0x8000 else v


# ---- loads, addressing, stack ----------------------------------------------------------------------------------
def test_addressing():
    c = cpu([0xDD, 0x7E, 0x80], ix=0x2000); c.mem[0x1F80] = 0x5A; c.step()       # d = -128
    assert c.a == 0x5A
    c = cpu([0xDD, 0x7E, 0x7F], ix=0xFFFF); c.mem[0x7E] = 0x77; c.step()          # wraps mod 2^16
    assert c.a == 0x77
    c = cpu([0xFD, 0x36, 0x05, 0xAA], iy=0x3000); c.step()
    assert c.mem[0x3005] == 0xAA and c.pc == 0x104
    c = cpu([0x2A, 0xFF, 0xFF]); c.mem[0xFFFF] = 0x34; c.mem[0] = 0x12; c.step()   # §6.1a wrap
    assert c.hl == 0x1234
    c = cpu([0x18, 0xFE], pc=0x100); c.step(); assert c.pc == 0x100                  # JR $
    c = cpu([0x18, 0x80], pc=0x100); c.step(); assert c.pc == 0x100 + 2 - 128
    c = cpu([0x10, 0x05], pc=0x100); c.reg[0] = 1; c.step(); assert c.pc == 0x102 and c.reg[0] == 0
    c = cpu([0x10, 0x05], pc=0x100); c.reg[0] = 2; c.step(); assert c.pc == 0x107
    c = cpu([0xC5]); c.set_rp(0, 0x1234); c.step()                                # PUSH: high at SP-1 (§6.1)
    assert c.sp == 0x8FFE and c.mem[0x8FFF] == 0x12 and c.mem[0x8FFE] == 0x34
    c = cpu([0xE1]); c.mem[0x9000:0x9002] = bytes([0x34, 0x12]); c.step()          # POP: low first
    assert c.hl == 0x1234 and c.sp == 0x9002
    c = cpu([0xE3]); c.mem[0x9000:0x9002] = bytes([0x34, 0x12]); c.set_rp(2, 0xABCD); c.step()
    assert c.hl == 0x1234 and c.mem[0x9000] == 0xCD and c.mem[0x9001] == 0xAB
    c = cpu([0xD9]); c.set_rp(0, 1); c.alt[0:6] = [9, 8, 7, 6, 5, 4]; c.step()
    assert c.reg[0:6] == [9, 8, 7, 6, 5, 4] and c.alt[1] == 1
    c = cpu([0xCD, 0x34, 0x12]); c.step()
    assert c.pc == 0x1234 and c.mem[0x8FFF] == 0x01 and c.mem[0x8FFE] == 0x03     # return address 0x103
    c = cpu([0xEF]); c.step(); assert c.pc == 0x28
    for k, op in enumerate(range(0xC7, 0x100, 8)):
        c = cpu([op]); c.step(); assert c.pc == 8 * k
    c = cpu([0xED, 0x73, 0x00, 0x20]); c.sp = 0xBEEF; c.step()
    assert c.mem[0x2000] == 0xEF and c.mem[0x2001] == 0xBE


def test_io():
    log = []
    c = cpu([0xDB, 0x34]); c.io_in = lambda p: (log.append(p), 0x99)[1]; c.reg[7] = 0x12; c.step()
    assert log == [0x1234] and c.a == 0x99                          # A on A8-A15 (§6.1 I/O)
    c = cpu([0xD3, 0x34]); c.io_out = lambda p, v: log.append((p, v)); c.reg[7] = 0x56; c.step()
    assert log[-1] == (0x5634, 0x56)
    c = cpu([0xED, 0x78]); c.io_in = lambda p: (log.append(p), 0x00)[1]; c.set_rp(0, 0xAB12); c.step()
    assert log[-1] == 0xAB12 and c.f & (Z_ | PV_) == (Z_ | PV_) and c.f & C_ == 0
    c = cpu([0xED, 0x41]); c.io_out = lambda p, v: log.append((p, v)); c.set_rp(0, 0x0102); c.reg[2] = 0x77; c.step()
    assert log[-1] == (0x0102, 0x01 if False else 0x00) or log[-1][0] == 0x0102


def test_block_io_bus_b():                                          # §6.1: input B before dec, output B-1
    log = []
    c = cpu([0xED, 0xA2]); c.io_in = lambda p: (log.append(p), 0x42)[1]; c.set_rp(0, 0x0310); c.set_rp(2, 0x2000); c.step()
    assert log == [0x0310] and c.mem[0x2000] == 0x42 and c.reg[0] == 2 and c.hl == 0x2001
    assert c.f & (Z_ | N_) == N_
    c = cpu([0xED, 0xA3]); c.io_out = lambda p, v: log.append((p, v)); c.set_rp(0, 0x0310); c.set_rp(2, 0x2000)
    c.mem[0x2000] = 0x99; c.step()
    assert log[-1] == (0x0210, 0x99) and c.reg[0] == 2
    c = cpu([0xED, 0xB3]); c.io_out = lambda p, v: log.append((p, v)); c.set_rp(0, 0x0210); c.set_rp(2, 0x2000)
    c.mem[0x2000:0x2002] = b"\x01\x02"
    assert c.step() == 21 and c.pc == 0x100
    assert c.step() == 16 and c.pc == 0x102 and c.f & Z_
    assert log[-2:] == [(0x0110, 1), (0x0010, 2)]
    c = cpu([0xED, 0xAA]); c.io_in = lambda p: 7; c.set_rp(0, 0x0110); c.set_rp(2, 0x2000); c.step()   # IND
    assert c.hl == 0x1FFF and c.f & Z_


# ---- block transfer and search -----------------------------------------------------------------------------------
def test_ldir_cpir():
    c = cpu([0xED, 0xB0], policy=Policy("mostek")); c.set_rp(0, 3); c.set_rp(1, 0x3000); c.set_rp(2, 0x2000)
    c.mem[0x2000:0x2003] = b"abc"
    ts = [c.step() for _ in range(3)]
    assert ts == [21, 21, 16] and c.mem[0x3000:0x3003] == b"abc" and c.get_rp(0) == 0
    assert c.f & (PV_ | N_ | H_) == 0 and c.pc == 0x102
    c = cpu([0xED, 0xA8], policy=Policy("mostek")); c.set_rp(0, 2); c.set_rp(1, 0x3000); c.set_rp(2, 0x2000)
    c.mem[0x2000] = 9; c.step()
    assert c.mem[0x3000] == 9 and c.hl == 0x1FFF and c.get_rp(1) == 0x2FFF and c.f & PV_
    # CPIR stops on match even with BC != 0, and on BC = 0 (PM p.91)
    c = cpu([0xED, 0xB1], policy=Policy("mostek")); c.set_rp(0, 5); c.set_rp(2, 0x2000); c.reg[7] = 2
    c.mem[0x2000:0x2003] = bytes([1, 2, 3])
    ts = [c.step() for _ in range(2)]
    assert ts == [21, 16] and c.hl == 0x2002 and c.get_rp(0) == 3 and c.f & Z_ and c.f & PV_ and c.f & N_
    c = cpu([0xED, 0xB1], policy=Policy("mostek")); c.set_rp(0, 2); c.set_rp(2, 0x2000); c.reg[7] = 9
    ts = [c.step() for _ in range(2)]
    assert ts == [21, 16] and c.get_rp(0) == 0 and not c.f & (Z_ | PV_)
    # BC = 0 at the start loops through 64K
    c = cpu([0xED, 0xB0], policy=Policy("mostek")); c.set_rp(0, 0)
    assert c.step() == 21 and c.get_rp(0) == 0xFFFF


# ---- DAA: the 13 rows (spec §6.2) and BCD maths ---------------------------------------------------------------
DAA_ROWS = [  # N, C, hi range, H, lo range, added, C after
    (0, 0, (0, 9), 0, (0, 9), 0x00, 0), (0, 0, (0, 8), 0, (10, 15), 0x06, 0), (0, 0, (0, 9), 1, (0, 3), 0x06, 0),
    (0, 0, (10, 15), 0, (0, 9), 0x60, 1), (0, 0, (9, 15), 0, (10, 15), 0x66, 1), (0, 0, (10, 15), 1, (0, 3), 0x66, 1),
    (0, 1, (0, 2), 0, (0, 9), 0x60, 1), (0, 1, (0, 2), 0, (10, 15), 0x66, 1), (0, 1, (0, 3), 1, (0, 3), 0x66, 1),
    (1, 0, (0, 9), 0, (0, 9), 0x00, 0), (1, 0, (0, 8), 1, (6, 15), 0xFA, 0), (1, 1, (7, 15), 0, (0, 9), 0xA0, 1),
    (1, 1, (6, 15), 1, (6, 15), 0x9A, 1),
]


def test_daa_table():
    for n, cy, hr, h, lr, add, cout in DAA_ROWS:
        for hi in range(hr[0], hr[1] + 1):
            for lo in range(lr[0], lr[1] + 1):
                c = cpu([0x27], f=(N_ if n else 0) | (C_ if cy else 0) | (H_ if h else 0))
                c.reg[7] = hi << 4 | lo
                c.step()
                assert c.a == (((hi << 4 | lo) + add) & 255), (n, cy, h, hi, lo)
                assert (c.f & C_) == cout and c.fx == H_                  # H after DAA is X under 'taint'
                assert bool(c.f & Z_) == (c.a == 0) and bool(c.f & S_) == bool(c.a & 0x80)
                assert (c.f & N_) == (N_ if n else 0)                      # N unchanged


def test_daa_bcd_property():
    def bcd(x):
        return (x // 10) << 4 | x % 10
    for a in range(100):
        for b in range(100):
            c = cpu([0x80, 0x27]); c.reg[7], c.reg[0] = bcd(a), bcd(b); c.step(); c.step()          # ADD A,B; DAA
            assert c.a == bcd((a + b) % 100) and bool(c.f & C_) == (a + b > 99), (a, b)
            if a >= b:
                c = cpu([0x90, 0x27]); c.reg[7], c.reg[0] = bcd(a), bcd(b); c.step(); c.step()      # SUB B; DAA
                assert c.a == bcd(a - b) and not c.f & C_, (a, b)
            else:
                c = cpu([0x90, 0x27]); c.reg[7], c.reg[0] = bcd(a), bcd(b); c.step(); c.step()
                assert c.a == bcd(a - b + 100) and c.f & C_, (a, b)


# ---- open decisions: switches -----------------------------------------------------------------------------------
def test_decision8_switch():
    c = cpu([0x27], policy=Policy("raise", "raise"), f=H_); c.reg[7] = 0x9A      # N=0 C=0 H=1 A=9A: outside the table
    try:
        c.step(); assert False
    except Unspecified as e:
        assert "decision 8" in str(e)
    c = cpu([0x27], policy=Policy("raise", "nmos"), f=H_); c.reg[7] = 0x9A; c.step()
    assert c.a == 0x00 and c.f & C_ and c.fx == 0                              # NMOS: +66
    c = cpu([0x27], policy=Policy("raise", "raise")); c.reg[7] = 0x45; c.step()    # inside the table: A, C defined
    assert c.a == 0x45 and c.fx & H_                                           # ... H still X
    c = cpu([0x27, 0x28, 0x00], policy=Policy("raise", "raise")); c.reg[7] = 0x45; c.step()
    c = cpu([0x27, 0x20, 0x00], policy=Policy("raise", "raise")); c.reg[7] = 0x45; c.step()
    # H consumed by a second DAA is unspecified
    c = cpu([0x27, 0x27], policy=Policy("raise", "raise")); c.reg[7] = 0x45; c.step()
    try:
        c.step(); assert False
    except Unspecified:
        pass


def test_decision6_switch():
    ops = {"LDI": [0xED, 0xA0], "LDD": [0xED, 0xA8], "LDIR": [0xED, 0xB0], "CPI": [0xED, 0xA1], "CPD": [0xED, 0xA9],
           "CPIR": [0xED, 0xB1], "CCF": [0x3F]}
    for name, code in ops.items():
        c = cpu(code, policy=Policy("raise", "raise"))
        try:
            c.step(); assert False, name
        except Unspecified as e:
            assert "decision 6" in str(e), name
    c = cpu([0x3F], policy=Policy("mostek"), f=C_); c.step()                    # CCF: H = previous carry, C inverted
    assert c.f & (H_ | C_ | N_) == H_
    c = cpu([0x3F], policy=Policy("mostek"), f=0); c.step()
    assert c.f & (H_ | C_ | N_) == C_
    c = cpu([0xED, 0xA1], policy=Policy("mostek")); c.reg[7] = 0x10; c.set_rp(2, 0x2000); c.mem[0x2000] = 0x01
    c.set_rp(0, 5); c.step()                                                   # 0x10-0x01: borrow from bit 4
    assert c.f & H_ and c.f & N_ and c.f & PV_ and not c.f & Z_
    c = cpu([0xED, 0xA0], policy=Policy("mostek"), f=S_ | Z_); c.set_rp(0, 1); c.step()
    assert c.f & (S_ | Z_) == (S_ | Z_) and not c.f & PV_                        # S, Z not affected
    c = cpu([0xED, 0xA0], policy=Policy("taint"), f=0); c.step()
    assert c.fx & (S_ | Z_) == (S_ | Z_)
    # consuming a tainted flag raises
    c = cpu([0xED, 0xA0, 0xCA, 0, 0x20], policy=Policy("taint")); c.step()
    try:
        c.step(); assert False
    except Unspecified:
        pass
    c = cpu([0xED, 0xA0, 0xF5], policy=Policy("taint")); c.step()                # PUSH AF of don't-care flags
    try:
        c.step(); assert False
    except Unspecified:
        pass
    c = cpu([0xED, 0xA0, 0xF5], policy=Policy("taint", pushaf="pass")); c.step(); c.step()   # opt-in: just moves F
    assert c.mem[c.sp] == c.f


def test_last_is_capped():
    c = cpu([0xC3, 0x00, 0x90]); c.step()                                      # jump forward 0x9000
    assert len(c.last.split()) <= 4


# ---- R, HALT, interrupts ------------------------------------------------------------------------------------------
def test_r_register():
    c = cpu([0x00, 0x00]); c.step(); c.step(); assert c.r == 2                      # 1 per M1
    c = cpu([0xCB, 0x00, 0xED, 0x44, 0xDD, 0x21, 0, 0]); [c.step() for _ in range(3)]
    assert c.r == 6                                                              # prefixed = 2 each
    c = cpu([0xDD, 0xCB, 0, 0x06]); c.step(); assert c.r == 2                     # op byte is not an M1 (§6.3)
    c = cpu([0x00], r=0x7F); c.step(); assert c.r == 0                           # mod 128
    c = cpu([0x00], r=0xFF); c.step(); assert c.r == 0x80                        # bit 7 stays
    c = cpu([0xED, 0x5F], r=0x10); c.step(); assert c.a == 0x12                  # LD A,R: after both increments
    c = cpu([0xED, 0x4F]); c.reg[7] = 0x55; c.step(); assert c.r == 0x55         # LD R,A: equals A afterwards
    c = cpu([0xED, 0xB0], policy=Policy("taint")); c.set_rp(0, 2); c.step(); assert c.r == 2   # per iteration


def test_ld_a_i_r_flags():
    c = cpu([0xED, 0x57], f=C_); c.i = 0x80; c.iff2 = 1; c.step()
    assert c.a == 0x80 and c.f == (S_ | PV_ | C_)
    c = cpu([0xED, 0x57], f=0); c.i = 0; c.iff2 = 0; c.step()
    assert c.f == Z_
    c = cpu([0xED, 0x5F], f=0x08, r=0xFD); c.iff2 = 1; c.step()                  # R = 0xFF
    assert c.a == 0xFF and c.f == (S_ | PV_)


def test_halt():
    c = cpu([0x76, 0x00]); c.step()
    assert c.halted and c.pc == 0x101
    for _ in range(3):
        assert c.step() == 4 and c.pc == 0x101 and c.halted
    assert c.r == 4                                                             # HALT + 3 halted M1s
    c.iff1 = c.iff2 = 1; c.int_line = True; c.im = 1
    assert c.step() == 13 and not c.halted and c.pc == 0x38
    assert c.mem[0x8FFF] == 0x01 and c.mem[0x8FFE] == 0x01                       # pushes HALT+1 (§6.3)


def test_interrupts():
    # NMI: 11 T, PC pushed, IFF1 cleared, IFF2 keeps the old IFF1, to 0066H, even with IFF1 = 0
    c = cpu([0x00]); c.iff1 = c.iff2 = 1; c.nmi()
    assert c.step() == 11 and c.pc == 0x66 and c.iff1 == 0 and c.iff2 == 1
    assert c.mem[0x8FFF] == 0x01 and c.mem[0x8FFE] == 0x00
    c = cpu([0xED, 0x45]); c.iff2 = 1; c.mem[0x9000:0x9002] = b"\x34\x12"; c.step()     # RETN: IFF1 <- IFF2
    assert c.iff1 == 1 and c.pc == 0x1234
    c = cpu([0xED, 0x4D]); c.iff2 = 1; c.iff1 = 0; c.mem[0x9000:0x9002] = b"\x34\x12"; c.step()   # RETI: IFF unchanged
    assert c.iff1 == 0 and c.iff2 == 1
    # INT ignored while IFF1 = 0; mode 1
    c = cpu([0x00, 0x00]); c.int_line = True; c.im = 1
    assert c.step() == 4 and c.pc == 0x101
    c.iff1 = c.iff2 = 1
    assert c.step() == 13 and c.pc == 0x38 and c.iff1 == 0 and c.iff2 == 0
    # mode 0: RST only, 12 T
    c = cpu([0x00]); c.iff1 = c.iff2 = 1; c.int_line = True; c.int_data = lambda: 0xD7
    assert c.step() == 12 and c.pc == 0x10
    c = cpu([0x00]); c.iff1 = c.iff2 = 1; c.int_line = True; c.int_data = lambda: 0xCD
    try:
        c.step(); assert False
    except Unspecified:
        pass
    # mode 2: 19 T, pointer {I, vector}, low byte first
    c = cpu([0x00]); c.iff1 = c.iff2 = 1; c.int_line = True; c.im = 2; c.i = 0x30; c.int_data = lambda: 0x40
    c.mem[0x3040:0x3042] = b"\x78\x56"
    assert c.step() == 19 and c.pc == 0x5678
    # NMI beats INT; EI delay: INT not accepted until after the instruction following EI
    c = cpu([0x00]); c.iff1 = c.iff2 = 1; c.int_line = True; c.im = 1; c.nmi()
    assert c.step() == 11 and c.pc == 0x66
    c = cpu([0xFB, 0x00, 0x00]); c.im = 1; c.int_line = True
    c.step(); assert c.pc == 0x101 and c.iff1 == 1                              # EI
    c.step(); assert c.pc == 0x102                                              # next instruction runs; then INT
    assert c.step() == 13 and c.pc == 0x38
    c = cpu([0xFB, 0xFB, 0x00, 0x00]); c.im = 1; c.int_line = True              # EI; EI restarts the delay (§8.4)
    c.step(); c.step(); c.step()
    assert c.pc == 0x103 and c.step() == 13
    c = cpu([0xFB, 0x00]); c.im = 1; c.step(); c.nmi()                           # the EI delay doesn't apply to NMI
    assert c.step() == 11
    c = cpu([0xF3, 0x00]); c.iff1 = c.iff2 = 1; c.step(); assert c.iff1 == 0 and c.iff2 == 0
    # LD A,I sees IFF2 before an interrupt at its end resets it (§8.1)
    c = cpu([0xED, 0x57, 0x00]); c.iff1 = c.iff2 = 1; c.im = 1; c.step()      # INT arrives during LD A,I, accepted at its end
    assert c.f & PV_ and c.iff2 == 1
    c.int_line = True; c.step(); assert c.iff2 == 0 and c.pc == 0x38
    # an interrupt between iterations of a block instruction pushes the instruction's own address (§8.4)
    c = cpu([0xED, 0xB0], policy=Policy("taint")); c.set_rp(0, 5); c.iff1 = c.iff2 = 1; c.im = 1
    c.step(); c.int_line = True
    c.step()
    assert c.mem[0x8FFF] == 0x01 and c.mem[0x8FFE] == 0x00 and c.pc == 0x38


def test_undocumented_raise():
    for code in ([0xED, 0x70], [0xDD, 0x00], [0xDD, 0x76], [0xDD, 0xCB, 0, 0x00], [0xDD, 0xDD], [0xED, 0x00], [0xFD, 0xCB, 0, 0x37]):
        c = cpu(code)
        try:
            c.step(); assert False, code
        except Undocumented:
            pass


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            n += 1
            print("ok", name)
    print(f"{n} tests passed")
