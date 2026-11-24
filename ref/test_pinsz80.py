#!/usr/bin/env python3
"""Self-tests for ref/pinsz80.py (Beru, chip-z80#8). Expected rows are typed from the draft spec tables
(§4.1-4.5, §4.7, §6.1, §8.4), not taken from the module's output.   Usage: python3 ref/test_pinsz80.py"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from refz80 import Policy, Unspecified, census  # noqa: E402
from pinsz80 import RecZ80, PinSim, tokens, COLS  # noqa: E402

fails = 0


def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  " + str(info)))
    fails += 0 if ok else 1


class Script:
    """Stimulus from lists: waits per T state, t1h changes by T1H number (0-based), vec."""

    def __init__(self, waits=(), t1h=None, rel=(), vec=0xFF):
        self.waits, self.t1h_map, self.rel, self.v = list(waits), t1h or {}, list(rel), vec
        self.nw = self.nt = 0

    def wait(self):
        self.nw += 1
        return self.waits[self.nw - 1] if self.nw <= len(self.waits) else 1

    def t1h(self, i, n, b):
        k = self.nt
        self.nt += 1
        return self.t1h_map.get(k, (i, n, b))

    def release(self):
        return self.rel.pop(0) if self.rel else True

    def vec(self, im):
        return self.v


def sim(prog, stim=None, steps=1, setup=None):
    c = RecZ80(Policy())
    c.mem[0:len(prog)] = bytes(prog)
    c.sp = 0x8000
    if setup:
        setup(c)
    s = PinSim(c, stim or Script())
    s.run(steps)
    return c, s


def rows(s, a=0, b=None):
    """Rows counted from the first T1H (the 10 power-up halves are skipped); values as strings, x = not compared."""
    from pinsz80 import _fmt
    out = []
    for h, p in s.rows[10 + a:(10 + b) if b is not None else None]:
        out.append({"t": h - 10, **{k: _fmt(p[k], 4 if k == "a" else 2 if k == "d_out" else 1) for k in COLS}})
    return out


def sel(r, *cols):
    return tuple(r[c] for c in cols)


# 1. every specified form (698 documented + 152 of §6.0a): T layout and event kinds agree with the model, in random states
forms, _ = census()
rnd = random.Random(5)
n = bad = 0
P = {"CB": 0xCB, "ED": 0xED, "DD": 0xDD, "FD": 0xFD}
for f in sorted(forms, key=str):
    for _ in range(6):
        c = RecZ80(Policy("taint", "taint"))
        for i in range(8): c.reg[i] = rnd.randrange(256)
        c.f, c.sp, c.ix, c.iy, c.pc = rnd.randrange(256), 0x8000, 0x5000, 0x5100, 0x100
        c.reg[2], c.reg[3] = 0x60, rnd.randrange(256)
        b = [f[1]] if f[0] == "main" else [P[f[0]], f[1]] if len(f) == 2 else [P[f[0]], 0xCB, rnd.randrange(8), f[2]]
        b += [rnd.randrange(256) for _ in range(4)]
        c.mem[0x100:0x100 + len(b)] = bytes(b)
        c.events = []
        try:
            T = c.step()
        except Unspecified:
            continue
        n += 1
        try:
            tokens(c.events, T)
        except Exception as e:
            bad += 1
            print("   layout", f, e)
check("T layout and bus-event kinds agree with the model for all %d forms (%d runs)" % (len(forms), n), bad == 0 and len(forms) == 850)

# 1b. power-up: 10 halves, nothing compared in 0-1, then bus_oe=0 with m1/halt/busak=1; first T1H at half 10 (§5 item 3a)
_, s = sim([0x00])
pu = [dict(zip(["h", "p"], r)) for r in s.rows[:11]]
check("§5 power-up: halves 0-1 uncompared, 2-9 floating with m1/halt/busak = 1, T1H at half 10 (a = 0000, m1_n = 0)",
      all(v is None for v in s.rows[0][1].values()) and all(v is None for v in s.rows[1][1].values())
      and all(s.rows[k][1]["bus_oe"] == 0 and s.rows[k][1]["m1_n"] == 1 and s.rows[k][1]["halt_n"] == 1
              and s.rows[k][1]["busak_n"] == 1 and s.rows[k][1]["a"] is None for k in range(2, 10))
      and s.rows[10][1]["a"] == 0 and s.rows[10][1]["m1_n"] == 0 and [r[5] for r in s.srows[:11]] == [0] * 8 + [1] * 3)

# 2. NOP M1, §4.1 table
_, s = sim([0x00])
r = rows(s)
exp = [("0000", 0, 1, 1, 1), ("0000", 0, 0, 0, 1), ("0000", 0, 0, 0, 1), ("0000", 0, 0, 0, 1),
       ("0000", 1, 1, 1, 0), ("0000", 1, 0, 1, 0), ("0000", 1, 0, 1, 0), ("0000", 1, 1, 1, 0)]
exp = [(a, str(m1), str(mq), str(rd), str(rf)) for a, m1, mq, rd, rf in exp]
check("§4.1 M1 table (NOP, 8 halves)", [sel(x, "a", "m1_n", "mreq_n", "rd_n", "rfsh_n") for x in r] == exp and len(r) == 8,
      [sel(x, "a", "m1_n", "mreq_n", "rd_n", "rfsh_n") for x in r])

# 3. refresh address {I,R}, R before increment, prefix counts twice (§6.3)
def st(c): c.i, c.r = 0x3E, 0x7F
_, s = sim([0x00, 0xCB, 0x00], steps=2, setup=st)
r = rows(s)
check("§4.1/§6.3 refresh address = {I, R before increment}, R wraps 7F->00 and CB counts",
      r[4]["a"] == "3e7f" and r[12]["a"] == "3e00" and r[20]["a"] == "3e01", (r[4]["a"], r[12]["a"], r[20]["a"]))

# 4. WAIT in M1: sampled at T2L, Tw repeats the T2 row (§4.1)
_, s = sim([0x00], Script(waits=[1, 0, 0, 1]))     # T1 w=1, T2 w=0 -> Tw w=0 -> Tw w=1 -> T3
r = rows(s)
check("§4.1 two wait states in M1 -> 12 halves, Tw rows = T2 rows",
      len(r) == 12 and all(sel(x, "m1_n", "mreq_n", "rd_n") == ("0", "0", "0") for x in r[3:8]) and r[8]["rfsh_n"] == "0",
      len(r))

# 5. memory write LD (HL),A, §4.2 table (a = HL, d_oe from T1L, wr_n low T2L..T3H)
def st(c): c.reg[4], c.reg[5], c.a = 0x40, 0x10, 0x5C
_, s = sim([0x77], setup=st)
r = rows(s, 8, 14)
check("§4.2 write cycle exact rows",
      [(x["mreq_n"], x["wr_n"], x["d_oe"]) for x in r] ==
      [("1", "1", "0"), ("0", "1", "1"), ("0", "1", "1"), ("0", "0", "1"), ("0", "0", "1"), ("1", "1", "1")]
      and all(x["a"] == "4010" for x in r) and all(x["d_out"] == "5c" for x in r[1:]), [(x["mreq_n"], x["wr_n"], x["d_oe"]) for x in r])

# 6. OUT (n),A: port rows (§4.3): A on A8-A15, iorq/wr fall at T2H, one automatic Tw*, 4 T
def st(c): c.a = 0xAB
_, s = sim([0xD3, 0x34], setup=st)
r = rows(s, 14, 22)
check("§4.3 OUT (n),A: 8 halves, a=ab34, iorq/wr low T2H..T3H, d_oe from T1L, mreq high",
      len(rows(s)) == 22 and all(x["a"] == "ab34" for x in r) and
      [x["iorq_n"] for x in r] == ["1", "1", "0", "0", "0", "0", "0", "1"] and
      [x["wr_n"] for x in r] == ["1", "1", "0", "0", "0", "0", "0", "1"] and
      [x["d_oe"] for x in r] == ["0", "1", "1", "1", "1", "1", "1", "1"] and all(x["mreq_n"] == "1" for x in r),
      [(x["iorq_n"], x["wr_n"]) for x in r])

# 7. lengthened cycles: LD SP,HL = OCF(6): T5,T6 inactive, a not compared (§6.1)
_, s = sim([0xF9])
r = rows(s)
check("§6.1 OCF(6): 12 halves, extra T strobes inactive and a = x",
      len(r) == 12 and all(x["a"] == "x" and x["mreq_n"] == "1" and x["rd_n"] == "1" and x["m1_n"] == "1" and x["rfsh_n"] == "1"
                           for x in r[8:]))

# 8. HALT: halt_n falls at T4L; halted M1s at HALT+1, 4 T each (§4.7, §6.3)
_, s = sim([0x76], steps=3)
r = rows(s)
check("§4.7 halt_n falls at T4L of HALT's M1; halted M1 fetches HALT+1",
      [x["halt_n"] for x in r[:8]] == ["1"] * 7 + ["0"] and all(x["halt_n"] == "0" for x in r[8:]) and
      r[8]["a"] == "0001" and r[16]["a"] == "0001" and len(r) == 24)

# 9. INT mode 1: INTA(7) SWH SWL = 13 T, iorq falls at Tw*1L, m1 low until T3H (§4.5, §8.2)
def st(c): c.iff1 = c.iff2 = 1; c.im = 1; c.pc = 0
stim = Script(t1h={0: (0, 1, 1)})     # INT low from the first T1H
c, s = sim([0x00, 0x00], stim, steps=2, setup=st)
r = rows(s)
ia = r[8:8 + 14]
check("§4.5/§8.2 mode-1 INTA 7 T + 2 pushes = 13 T, PC=0038", len(r) == 8 + 26 and c.pc == 0x38, (len(r), hex(c.pc)))
check("§4.5 INTA rows: iorq low from Tw*1L to T3L start, m1 low until T3H, no mreq before T3L, T5 idle",
      [x["iorq_n"] for x in ia] == ["1"] * 5 + ["0"] * 3 + ["1"] * 6 and [x["m1_n"] for x in ia] == ["0"] * 8 + ["1"] * 6
      and [x["mreq_n"] for x in ia] == ["1"] * 9 + ["0", "0"] + ["1"] * 3 and ia[12]["a"] == "x" and ia[8]["rfsh_n"] == "0",
      [(x["iorq_n"], x["m1_n"], x["mreq_n"]) for x in ia])

# 10. BUSRQ: sampled at the last T of an M cycle, buses float from the next rising edge, busak low (§4.4)
stim = Script(t1h={1: (1, 1, 0)}, rel=[False, True])   # BUSRQ low at the T1H of M2 of LD HL,nn (M2 is not the last cycle)
c, s = sim([0x21, 0x34, 0x12], stim)
r = rows(s)
check("§4.4 BUSRQ in M2: floats after its T3, busak low 3 Tx (released at Tx2, seen at Tx3), then M3 runs",
      len(r) == 8 + 6 + 6 + 6 and [x["bus_oe"] for x in r[14:20]] == ["0"] * 6
      and [x["busak_n"] for x in r[14:20]] == ["0", "0", "0", "0", "0", "1"] and all(x["bus_oe"] == "1" for x in r[20:])
      and all(x["a"] == "x" and x["mreq_n"] == "x" and x["d_oe"] == "0" for x in r[14:20]) and r[20]["a"] == "0002",
      (len(r), [(x["bus_oe"], x["busak_n"]) for x in r[12:21]]))

# 11. EI delay: INT held low is not taken after EI, nor after the next instruction... only after the one following EI (§8.1, §8.4)
def st(c): c.im = 1
stim = Script(t1h={0: (0, 1, 1)})
c, s = sim([0xFB, 0x00, 0x00, 0x00], stim, steps=4, setup=st)
kinds = [k for _, _, k in s.idx]
check("§8.1 EI; NOP; INT taken after the NOP (not after EI)", kinds[:3] == ["I FB", "I 00", "INT1"], kinds)

# 12. NMI: edge pending, taken at the end of the instruction, 11 T, halt_n etc., first handler instruction always runs (§8.4 item 6)
def st(c): c.pc = 0
stim = Script(t1h={0: (1, 0, 1), 1: (1, 1, 1), 2: (1, 0, 1)})
c, s = sim([0x00] * 8, stim, steps=5, setup=st)
kinds = [k for _, _, k in s.idx]
check("§8.4 NMI taken after the first NOP; the handler's first instruction runs before a second NMI",
      kinds[:4] == ["I 00", "NMI", "I 00", "NMI"], kinds)

print("FAIL" if fails else "PASS", "pinsz80 self-tests, %d failing" % fails)
sys.exit(1 if fails else 0)
