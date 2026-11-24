#!/usr/bin/env python3
"""C8 random-program generator (Beru, chip-z80#8). Spec: draft docs/z80/spec.md §7 C8, §6.0, §8.4.

One seed -> a 64 KiB memory image, a stimulus trace and the reference model's pin trace:
  python3 tests/random/gen.py --seed 7 --out build/c8/s7 [--instr 1500]
writes <out>.hex (readmemh, one byte per line), <out>.pins (expected pin trace, ref/pinsz80.py columns),
<out>.stim (inputs per half T: wait_n int_n nmi_n busrq_n vec), <out>.idx (instruction starts) and <out>.cov.json.
The testbench replays .hex and .stim open-loop on the RTL and dumps a trace in the .pins format; compare.py diffs.

Programs are generated while the reference model runs: at each PC with no code yet, a random documented form is
drawn, trial-run on a copy of the CPU, and kept only if it is determined (no Undocumented/Unspecified), writes
only to data memory (>= 0x4000), keeps SP and I in range and lands PC in code. Code bytes that were fetched or
read are frozen, so the final image replays the same run. Layout:
  0000        JP 0100        0008..0038  RST stubs (also mode-0 INT vectors; 0038 is the mode-1 vector)
  0066        NMI handler    0100..37FF  preamble then random code      3800..39FF  IM 2 handler stubs
  3C00..3FFF  IM 2 vector tables (I in 3C..3F)      4000..FFFF  data (random bytes), stack
Handlers use only register instructions that cannot raise, so they are safe in any state.
"""
import argparse
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "ref"))
from refz80 import Policy, Undocumented, Unspecified, census  # noqa: E402
from pinsz80 import RecZ80, PinSim, CODE_LIMIT, io_value  # noqa: E402

CODE_END = 0x3800
STUBS = 0x3800
DATA = 0x4000

# Forms the model raises Unspecified on in EVERY state under the default policy (§3 decisions 6 and 8).
# One place: when Sai settles decisions 6/8, delete the rows here (and set the model's Policy), nothing else.
EXCLUDED = {
    ("ED", 0xA0): "decision 6: S/Z after LDI", ("ED", 0xA8): "decision 6: S/Z after LDD",
    ("ED", 0xB0): "decision 6: S/Z after LDIR", ("ED", 0xB8): "decision 6: S/Z after LDDR",
    ("ED", 0xA1): "decision 6: H after CPI", ("ED", 0xA9): "decision 6: H after CPD",
    ("ED", 0xB1): "decision 6: H after CPIR", ("ED", 0xB9): "decision 6: H after CPDR",
    ("main", 0x3F): "decision 6: H after CCF",
}
# Not excluded, but only determined in some states: DAA outside the 13-row table (decision 8) and every
# consumer of a don't-care flag raise Unspecified at run time, and the generator's trial-run rejects those states.

JP_REG = {("main", 0xE9), ("DD", 0xE9), ("FD", 0xE9)}
SAFE_BODY = [  # register-only, never raise, never touch memory/SP/IFF: handler bodies
    [0x00], [0x04], [0x05], [0x0C], [0x0D], [0x14], [0x15], [0x1C], [0x1D], [0x24], [0x25], [0x2C], [0x2D],
    [0x3C], [0x3D], [0x47], [0x50], [0x61], [0x78], [0x2F], [0x37], [0x07], [0x0F], [0xEB], [0xD9], [0x08],
    [0x80], [0x91], [0xA2], [0xB3], [0xAC], [0xBD], [0xED, 0x44], [0xCB, 0x00], [0xCB, 0x1F], [0xCB, 0x48],
    [0x03], [0x1B], [0x23], [0x06, 0x5A], [0x3E, 0xC3], [0xC6, 0x11], [0xE6, 0x0F],
]


def forms_allowed():
    forms, _ = census()
    return sorted((f for f in forms if f not in EXCLUDED), key=str), sorted(forms, key=str)


FORMS, ALL_FORMS = forms_allowed()


def form_key(ev):
    """Form of an executed instruction from its recorded events (same keys as census())."""
    ocf = [e for e in ev if e[0] == "OCF"]
    od = [e for e in ev if e[0] == "OD"]
    b0 = ocf[0][2]
    if b0 == 0xCB: return ("CB", ocf[1][2])
    if b0 == 0xED: return ("ED", ocf[1][2])
    if b0 in (0xDD, 0xFD):
        n = "DD" if b0 == 0xDD else "FD"
        return (n, "CB", od[1][2]) if ocf[1][2] == 0xCB else (n, ocf[1][2])
    return ("main", b0)


def opcode_bytes(f):
    P = {"CB": 0xCB, "ED": 0xED, "DD": 0xDD, "FD": 0xFD}
    if f[0] == "main": return [f[1]]
    if len(f) == 3: return [P[f[0]], 0xCB, None, f[2]]       # DD CB d op: d at index 2
    return [P[f[0]], f[1]]


def operand_kind(f):
    """How the operand bytes after the opcode are used (decides what to randomise)."""
    if f[0] == "main":
        op = f[1]
        x, z = op >> 6, op & 7
        if op in (0x10, 0x18, 0x20, 0x28, 0x30, 0x38): return "rel"
        if op in (0xC3, 0xCD) or (x == 3 and z in (2, 4)): return "target"
        if op in (0x22, 0x2A, 0x32, 0x3A): return "addr"
        if op in (0x01, 0x11, 0x21, 0x31): return "imm16"
        if op in (0xD3, 0xDB): return "port"
        return "imm8"
    if f[0] == "ED":
        op = f[1]
        return "addr" if op >> 6 == 1 and op & 7 == 3 else "none"
    if f[0] in ("DD", "FD"):
        op = f[1] if len(f) == 2 else None
        if op in (0x22, 0x2A): return "addr"
        if op == 0x21: return "imm16"
        if op == 0x36: return "dispimm"
        if op in (0x26, 0x2E): return "imm8"             # §6.0a U1: LD IXH/IXL/IYH/IYL,n
        if op is not None and (op >> 6 == 1 and op & 7 != 6 and op >> 3 & 7 != 6 or op >> 6 == 2 and op & 7 in (4, 5)
                               or op in (0x24, 0x25, 0x2C, 0x2D)):
            return "none"                                # §6.0a U1/U2: no operand bytes
        return "disp"
    return "none"


class Stim:
    """Random WAIT/INT/NMI/BUSRQ stimulus. Legality is enforced by PinSim; this only proposes."""

    def __init__(self, rng, prof):
        self.rng, self.prof = rng, prof
        self.acked = False

    def wait(self):
        return 0 if self.rng.random() < self.prof["wait"] else 1

    def t1h(self, i, n, b):
        r, p = self.rng, self.prof
        if i == 1:
            if r.random() < p["int"]: i = 0
        elif r.random() < (0.9 if self.acked else p["int_rel"]):
            i, self.acked = 1, False
        if n == 1:
            if r.random() < p["nmi"]: n = 0
        elif r.random() < 0.5:
            n = 1
        if b == 1 and r.random() < p["busrq"]:
            b = 0
        return i, n, b

    def release(self):
        return self.rng.random() < 0.4

    def vec(self, im):
        self.acked = True
        r = self.rng
        if im == 0: return 0xC7 | (r.randint(1, 7) << 3)       # RST p, p != 0 (RST 0 would restart the preamble)
        if im == 2: return r.randrange(256) & 0xFE
        return r.randrange(256)


PROFILES = [
    dict(name="quiet", wait=0.0, int=0.0, int_rel=0.3, nmi=0.0, busrq=0.0),
    dict(name="waits", wait=0.3, int=0.0, int_rel=0.3, nmi=0.0, busrq=0.0),
    dict(name="int", wait=0.05, int=0.02, int_rel=0.2, nmi=0.0, busrq=0.0),
    dict(name="nmi", wait=0.05, int=0.0, int_rel=0.3, nmi=0.02, busrq=0.0),
    dict(name="busrq", wait=0.1, int=0.0, int_rel=0.3, nmi=0.0, busrq=0.05),
    dict(name="all", wait=0.1, int=0.02, int_rel=0.2, nmi=0.01, busrq=0.03),
    dict(name="heavy", wait=0.5, int=0.05, int_rel=0.1, nmi=0.03, busrq=0.1),
]


class Gen:
    def __init__(self, seed, instr):
        self.rng = random.Random(seed * 7919 + 13)
        self.seed, self.limit = seed, instr
        self.mem = bytearray(65536)
        self.code = set()                 # addresses written by the generator (instruction bytes)
        self.frozen = set()               # addresses fetched or read: never rewritten
        self.starts = []
        self.hits = {}                    # executed form -> count
        self.n = 0
        self.rej = 0
        self.fallback = 0
        self.force = None
        self.from_walk, self.walk_try = False, 0
        off = (seed * 211) % len(FORMS)
        self.walk, self.wi = FORMS[off:] + FORMS[:off], 0
        self.prof = PROFILES[seed % len(PROFILES)]
        self.build_fixed()

    # -- fixed code -------------------------------------------------------------------------------------
    def body(self, n):
        out = []
        for _ in range(n):
            out += self.rng.choice(SAFE_BODY)
        return out

    def put(self, a, b):
        self.mem[a:a + len(b)] = bytes(b)

    def build_fixed(self):
        r = self.rng
        self.put(0, [0xC3, 0x00, 0x01])
        for p in range(8, 0x40, 8):       # RST stubs: body, EI, RETI (8 bytes)
            self.put(p, (self.body(2) + [0xFB, 0xED, 0x4D])[:8] if p != 0x38 else self.body(2) + [0xFB, 0xED, 0x4D])
        self.put(0x66, self.body(3) + [0xED, 0x45])           # NMI: body, RETN
        stubs = []
        for k in range(16):
            a = STUBS + 16 * k
            self.put(a, self.body(3) + [0xFB, 0xED, 0x4D])
            stubs.append(a)
        for a in range(0x3C00, 0x4000, 2):
            s = r.choice(stubs)
            self.mem[a], self.mem[a + 1] = s & 255, s >> 8
        for a in range(DATA, 65536):
            self.mem[a] = r.randrange(256)
        self.init_data = bytes(self.mem[DATA:])     # the run mutates data memory; the replayed image keeps this
        # preamble at 0100: every register written before it is read (§5 decision 1)
        pre = [0xF3]
        pre += [0x31, 0x00, 0xF0]                                          # LD SP,F000
        pre += [0x3E, 0x3C + r.randrange(4), 0xED, 0x47]                   # LD A,3x ; LD I,A
        pre += [0x3E, r.randrange(256), 0xED, 0x4F]                        # LD A,r ; LD R,A
        pre += [0xED, (0x46, 0x56, 0x5E)[r.randrange(3)]]                  # IM 0/1/2
        def ptr(): return r.randrange(0x4000, 0xE000)
        for op in (0x01, 0x11, 0x21):                                      # BC DE HL
            v = ptr(); pre += [op, v & 255, v >> 8]
        pre += [0x3E, r.randrange(256)]                                    # LD A,n
        pre += [0xD9]                                                       # EXX: other set
        for op in (0x01, 0x11, 0x21):
            v = ptr(); pre += [op, v & 255, v >> 8]
        pre += [0xD9]
        for pf in (0xDD, 0xFD):
            v = ptr(); pre += [pf, 0x21, v & 255, v >> 8]
        pre += [0x01, r.randrange(256), r.randrange(256), 0xC5, 0xF1]      # LD BC,nn ; PUSH BC ; POP AF (A,F random)
        pre += [0x08, 0x3E, r.randrange(256), 0x01, r.randrange(256), r.randrange(256), 0xC5, 0xF1, 0x08]  # AF'
        if r.random() < 0.7:
            pre += [0xFB]
        self.put(0x100, pre)
        self.code |= set(range(0x100, 0x100 + len(pre)))
        self.entry_end = 0x100 + len(pre)

    # -- instruction generation ---------------------------------------------------------------------------
    def pick_target(self, pc):
        r = self.rng
        k = r.random()
        if k < 0.55: return pc + 2 + r.randrange(2, 60)
        if k < 0.70 and self.starts: return r.choice(self.starts)
        return r.randrange(0x100, 0x3000)

    def pick_form(self):
        """Uniform random, but half of the picks walk a seed-specific rotation of all forms, so a few dozen seeds
        reach even the forms that need a rare state."""
        self.from_walk = self.rng.random() < 0.5
        if self.from_walk:
            return self.walk[self.wi % len(self.walk)]
        return self.rng.choice(FORMS)

    def make(self, f, pc):
        r = self.rng
        b = opcode_bytes(f)
        kind = operand_kind(f)
        def d16(v): return [v & 255, v >> 8]
        data = lambda: r.randrange(DATA, 0xFFF0) if r.random() < 0.85 else r.randrange(0, 0x4000)
        if kind == "rel": b += [(r.randrange(-8, 30)) & 255]
        elif kind == "target": b += d16(self.pick_target(pc))
        elif kind == "addr": b += d16(data())
        elif kind == "imm16": b += d16(r.randrange(0x4010, 0xFFF0) if r.random() < 0.85 else r.randrange(65536))
        elif kind == "imm8" or kind == "port": b += [r.randrange(256)]
        elif kind == "disp": b += [r.randrange(256)]
        elif kind == "dispimm": b += [r.randrange(256), r.randrange(256)]
        if len(f) == 3:
            b[2] = r.randrange(256)
        return [x for x in b if x is not None] if len(f) != 3 else b

    def trial(self, cpu, pc, raw):
        """Run `raw` at pc on a copy. Returns (ok, nbytes)."""
        c = cpu.clone()
        c.mem[pc:pc + len(raw)] = bytes(raw)
        c.events = []
        c.nmi_pending = c.int_line = False
        try:
            c.step()
        except (Undocumented, Unspecified):
            return False, 0
        if any(e[0] == "MW" and e[1] < DATA for e in c.events):
            return False, 0
        if not (0x4010 <= c.sp <= 0xFFF0) or not (0x3C <= c.i <= 0x3F):
            return False, 0
        if c.halted and not ((c.iff1 and self.prof["int"] > 0) or self.prof["nmi"] > 0):
            return False, 0                  # nothing could end the halt
        ocf = [e for e in c.events if e[0] == "OCF"]
        is_rst = len(ocf) == 1 and ocf[0][2] & 0xC7 == 0xC7 and not c.halted      # only RST enters the stubs
        if not (0x100 <= c.pc < CODE_END or (is_rst and c.pc in range(0, 0x40, 8))):
            return False, 0
        n = sum(1 for e in c.events if e[0] in ("OCF", "OD"))
        return True, n

    def ensure(self, cpu):
        pc = cpu.pc
        if pc < self.entry_end and pc >= 0x100 or pc < 0x100 or pc >= CODE_END:
            return True                      # fixed handler code, safe by construction
        for _ in range(40):
            if pc in self.code:
                ok, n = self.trial(cpu, pc, bytes(self.mem[pc:pc + 4]))
                if ok:
                    return True
                if any(a in self.frozen for a in range(pc, pc + 4)):
                    return False             # state-dependent dead end on executed bytes
                self.code -= set(range(pc, pc + 4))
            f = self.force or self.pick_form()
            self.force = None
            raw = self.make(f, pc)
            ok, n = self.trial(cpu, pc, raw + [0] * (4 - len(raw)))
            if not ok and f in JP_REG and self.rng.random() < 0.8:
                # JP (HL)/(IX)/(IY) only lands in code if the register points there: load it first, jump next
                raw = {("main", 0xE9): [0x21], ("DD", 0xE9): [0xDD, 0x21], ("FD", 0xE9): [0xFD, 0x21]}[f]
                t = self.pick_target(pc + 4)
                raw = raw + [t & 255, t >> 8]
                ok, n = self.trial(cpu, pc, raw + [0] * (4 - len(raw)))
                if ok:
                    self.force = f
            if self.from_walk and f == self.walk[self.wi % len(self.walk)]:
                self.walk_try += 1
                if ok or self.walk_try >= 8:       # retry a rotation form 8 times (new operands/state) before moving on
                    self.wi += 1
                    self.walk_try = 0
            if not ok:
                self.rej += 1
                continue
            span = range(pc, pc + len(raw))
            if any(a in self.code or a in self.frozen or a >= CODE_END for a in span):
                self.rej += 1
                continue
            self.put(pc, raw)
            self.code |= set(span)
            self.starts.append(pc)
            return True
        self.fallback += 1
        if any(a in self.frozen for a in range(pc, pc + 1)):
            return False
        self.put(pc, [0x00])
        self.code.add(pc)
        return True

    def seen(self, ev):
        for e in ev:
            if e[0] in ("OCF", "OD", "MR") and e[1] < DATA:
                self.frozen.add(e[1])
        if any(e[0] == "OCF" for e in ev):
            f = form_key(ev)
            self.hits[f] = self.hits.get(f, 0) + 1
            self.n += 1

    def write_hex(self, path):
        with open(path, "w") as f:
            f.write("\n".join("%02x" % b for b in bytes(self.mem[:DATA]) + self.init_data) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--instr", type=int, default=1500)
    a = ap.parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    g = Gen(a.seed, a.instr)
    # run until `instr` instructions have executed
    cpu = RecZ80(Policy())
    cpu.mem = g.mem
    g_stim = Stim(random.Random(a.seed * 104729 + 7), g.prof)
    sim = PinSim(cpu, g_stim, g)
    g.limit_hit = False
    steps = 0
    while g.n < a.instr and sim.stop_reason == "limit" and steps < a.instr * 6:
        sim.run(200)
        steps += 200
        if sim.stop_reason != "limit":
            break
    sim.write(a.out)
    g.write_hex(a.out + ".hex")
    case = sim.write_vectors(a.out + ".vec", os.path.basename(a.out), bytes(g.mem[:DATA]) + g.init_data)
    open(a.out + ".case", "w").write(case + "\n")
    cov = dict(seed=a.seed, profile=g.prof["name"], instr=g.n, halves=sim.h, stop=sim.stop_reason,
               rejected=g.rej, fallback_nops=g.fallback, stim=sim.cov,
               forms={"/".join(str(x) if not isinstance(x, int) else "%02X" % x for x in k): v for k, v in g.hits.items()})
    with open(a.out + ".cov.json", "w") as f:
        json.dump(cov, f, indent=1, sort_keys=True)
    print("seed %d profile %s: %d instructions, %d halves, stop=%s" % (a.seed, g.prof["name"], g.n, sim.h, sim.stop_reason))


if __name__ == "__main__":
    main()
