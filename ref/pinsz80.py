#!/usr/bin/env python3
"""Z80 pin-level view of the reference model (Beru, chip-z80#8). Spec: draft docs/z80/spec.md @ 696e137.

refz80.Z80 gives architectural state and T-state totals. This module wraps it to say what every pin does in
every half T state (§4.0 model clock: TnH, TnL), with WAIT, INT, NMI and BUSRQ stimulus (§4.4-4.7, §8.4).

How: RecZ80 records the bus events of each step (opcode fetches with I/R, operand reads, memory reads/writes,
port reads/writes). `tokens()` gives the M-cycle layout of the instruction from §6.1 (F=OCF, D=operand read,
R=memory read, W=memory write, P/Q=port read/write, I=internal), and the cycle emitters turn each cycle into
half-T pin rows per §4.1-4.5. The token layout is checked against the model's own T count on every step
(a mismatch raises), so a wrong template can't pass silently.

Trace (.pins), one row per half T state, in the column layout the z80_system testbench dumps (+TRACE=):
  half a d_out d_oe m1_n mreq_n iorq_n rd_n wr_n rfsh_n halt_n busak_n bus_oe | wait_n int_n nmi_n busrq_n reset_n d_in
`x` in an expected trace = not compared. Half 0 is the first rising edge with reset_n low: the trace starts with the
power-up reset (reset_n low for halves 0-7, high from half 8, first T1H at half 10, as zbus.powerup() and spec v1 §5).
Stimulus (.stim): half wait_n int_n nmi_n busrq_n reset_n vec. `vec` is the byte the interrupting device holds on d_in
during an INTA (held from that INTA's T1H); the stock tb drives FFH, so C8 needs the tb to read it (see README).
Vector files for the tb (write_vectors): prog.hex stim.hex exp.hex mask.hex inp.hex vec.hex, same packing as tb.sv.
Port reads return io_value(addr): low byte ^ A5H, like the tb.

Decisions this module takes where the draft spec is silent are listed in README.md (tests/random) and filed
as Igris issues; each is marked `# SPEC-GAP n` here.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from refz80 import Z80, Policy, Undocumented, Unspecified  # noqa: E402

COLS = ["a", "m1_n", "mreq_n", "iorq_n", "rd_n", "wr_n", "rfsh_n", "halt_n", "busak_n", "bus_oe", "d_oe", "d_out"]
STIM_COLS = ["wait_n", "int_n", "nmi_n", "busrq_n", "reset_n", "vec"]
POWERUP_E = 8           # reset_n rises at half 8; first T1H at half 10 (spec v1 §5 item 3a)
CODE_LIMIT = 0x3C00     # generator layout: code below, I-register vector tables 3C00-3FFF, data from 4000


def io_value(addr):
    """Value an IN/INI/IND cycle reads from port address `addr`: low byte ^ A5H, as the z80_system testbench
    (tb/z80_bus/z80_system.sv, chip-z80#12) does."""
    return (addr & 0xFF) ^ 0xA5


class RecZ80(Z80):
    """Z80 that records the bus events of each step()."""

    def __init__(self, policy=None, mem=None):
        super().__init__(policy, mem)
        self.events = []
        self._io_in = io_value
        self.io_in = self._rec_in
        self.io_out = self._rec_out

    def _rec_in(self, port):
        v = self._io_in(port) & 255
        self.events.append(("PR", port & 0xFFFF, v))
        return v

    def _rec_out(self, port, v):
        self.events.append(("PW", port & 0xFFFF, v & 255))

    def m1(self):
        self.events.append(["M1", self.pc, self.i, self.r])
        super().m1()

    def fetch(self):
        addr = self.pc
        v = super().fetch()
        if self.events and isinstance(self.events[-1], list):
            e = self.events[-1]
            self.events[-1] = ("OCF", addr, v, e[2], e[3])
        else:
            self.events.append(("OD", addr, v))
        return v

    def rd(self, a):
        v = super().rd(a)
        self.events.append(("MR", a & 0xFFFF, v))
        return v

    def wr(self, a, v):
        super().wr(a, v)
        self.events.append(("MW", a & 0xFFFF, v & 255))

    def clone(self):
        import copy
        c = copy.copy(self)
        c.mem = bytearray(self.mem)
        c.reg, c.alt = list(self.reg), list(self.alt)
        c.events = []
        return c


def _evs(events):
    """Normalise: a lone M1 marker (no fetch followed) becomes a dummy OCF at that PC."""
    out = []
    for e in events:
        if isinstance(e, list):
            out.append(("OCFX", e[1], None, e[2], e[3]))
        else:
            out.append(e)
    return out


# ---- §6.1 M-cycle layout -------------------------------------------------------------------------------
def tokens(events, T):
    """M-cycle tokens for the instruction that just ran. F4/F5/F6 OCF, D3/D4/D5 operand read, R3/R4 memory read,
    W3/W5 memory write, P port read, Q port write, I<n> internal. `swap` True: the last two writes go high byte
    first (EX (SP),HL: SWH then SWL). Raises if a layout and the model disagree on T or on the event count."""
    ev = _evs(events)
    ocf = [e for e in ev if e[0] == "OCF"]
    od = [e for e in ev if e[0] == "OD"]
    b0 = ocf[0][2]
    swap = False
    tk = []
    x, y, z = b0 >> 6, (b0 >> 3) & 7, b0 & 7
    q = y & 1
    if b0 == 0xCB:
        op = ocf[1][2]
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        tk = ["F4", "F4"] + (["R4"] + ([] if x == 1 else ["W3"]) if z == 6 else [])
    elif b0 == 0xED:
        op = ocf[1][2]
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        q = y & 1
        rep = T == 21
        if x == 1:
            if z == 0: tk = ["F4", "F4", "P4"]
            elif z == 1: tk = ["F4", "F4", "Q4"]
            elif z == 2: tk = ["F4", "F4", "I4", "I3"]
            elif z == 3: tk = ["F4", "F4", "D3", "D3"] + (["W3", "W3"] if q == 0 else ["R3", "R3"])
            elif z == 5: tk = ["F4", "F4", "R3", "R3"]
            elif z in (4, 6): tk = ["F4", "F4"]
            elif z == 7: tk = ["F4", "F5"] if y < 4 else ["F4", "F4", "R3", "I4", "W3"]
        elif x == 2:
            tk = {0: ["F4", "F4", "R3", "W5"], 1: ["F4", "F4", "R3", "I5"],
                  2: ["F4", "F5", "P4", "W3"], 3: ["F4", "F5", "R3", "Q4"]}[z] + (["I5"] if rep else [])
    elif b0 in (0xDD, 0xFD):
        op = ocf[1][2]
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        if op == 0xCB:
            op2 = od[1][2]
            tk = ["F4", "F4", "D3", "D5", "R4"] + ([] if op2 >> 6 == 1 else ["W3"])
        elif op in (0x34, 0x35):
            tk = ["F4", "F4", "D3", "I5", "R4", "W3"]
        elif op == 0x36:
            tk = ["F4", "F4", "D3", "D5", "W3"]
        elif x == 2 and z == 6 or x == 1 and z == 6:
            tk = ["F4", "F4", "D3", "I5", "R3"]
        elif x == 1 and y == 6:
            tk = ["F4", "F4", "D3", "I5", "W3"]
        elif x == 0 and z == 1 and (y & 1):
            tk = ["F4", "F4", "I4", "I3"]
        else:
            tk = {0x21: ["F4", "F4", "D3", "D3"], 0x22: ["F4", "F4", "D3", "D3", "W3", "W3"],
                  0x2A: ["F4", "F4", "D3", "D3", "R3", "R3"], 0x23: ["F4", "F6"], 0x2B: ["F4", "F6"],
                  0xE1: ["F4", "F4", "R3", "R3"], 0xE5: ["F4", "F5", "W3", "W3"],
                  0xE3: ["F4", "F4", "R3", "R4", "W3", "W5"], 0xE9: ["F4", "F4"], 0xF9: ["F4", "F6"]}[op]
            swap = op == 0xE3
    else:
        p = y >> 1
        if x == 1:
            tk = ["F4", "R3"] if z == 6 and y != 6 else ["F4", "W3"] if y == 6 and z != 6 else ["F4"]
        elif x == 2:
            tk = ["F4", "R3"] if z == 6 else ["F4"]
        elif x == 0:
            if z == 0:
                tk = ["F4"] if y < 2 else ["F5", "D3"] + (["I5"] if T == 13 else []) if y == 2 \
                    else ["F4", "D3"] + (["I5"] if T == 12 else [])
            elif z == 1: tk = ["F4", "D3", "D3"] if q == 0 else ["F4", "I4", "I3"]
            elif z == 2:
                tk = ["F4", "W3"] if y in (0, 2) else ["F4", "R3"] if y in (1, 3) else \
                    ["F4", "D3", "D3"] + {4: ["W3", "W3"], 5: ["R3", "R3"], 6: ["W3"], 7: ["R3"]}[y]
            elif z == 3: tk = ["F6"]
            elif z in (4, 5): tk = ["F4", "R4", "W3"] if y == 6 else ["F4"]
            elif z == 6: tk = ["F4", "D3", "W3"] if y == 6 else ["F4", "D3"]
            else: tk = ["F4"]
        else:
            if z == 0: tk = ["F5"] + (["R3", "R3"] if T == 11 else [])
            elif z == 1:
                tk = ["F4", "R3", "R3"] if q == 0 or p == 0 else ["F6"] if p == 3 else ["F4"]
            elif z == 2: tk = ["F4", "D3", "D3"]
            elif z == 3:
                tk = {0: ["F4", "D3", "D3"], 2: ["F4", "D3", "Q4"], 3: ["F4", "D3", "P4"],
                      4: ["F4", "R3", "R4", "W3", "W5"]}.get(y, ["F4"])
                swap = y == 4
            elif z == 4: tk = ["F4", "D3", "D3"] if T == 10 else ["F4", "D3", "D4", "W3", "W3"]
            elif z == 5: tk = ["F5", "W3", "W3"] if q == 0 else ["F4", "D3", "D4", "W3", "W3"]
            elif z == 6: tk = ["F4", "D3"]
            else: tk = ["F5", "W3", "W3"]
    _check(tk, ev, T)
    return tk, swap


def tok_t(t):
    return int(t[1:])


def _check(tk, ev, T):
    tot = sum(tok_t(t) for t in tk)
    kinds = {"F": "OCF", "D": "OD", "R": "MR", "W": "MW", "P": "PR", "Q": "PW"}
    want = [kinds[t[0]] for t in tk if t[0] != "I"]
    got = [e[0] for e in ev]
    if tot != T or want != got:
        raise AssertionError(f"layout {tk} (T={tot}) vs model T={T}, events {got}")


def cycles_from_tokens(tk, ev, swap):
    """-> list of dicts: kind, T, addr, data, i, r (OCF)."""
    ev = list(_evs(ev))
    if swap:                                    # EX (SP),HL/IX/IY: SRL SRH SWH SWL (§6.1 note)
        ev[-2], ev[-1] = ev[-1], ev[-2]
    out, k = [], 0
    for t in tk:
        n = tok_t(t)
        if t[0] == "I":
            out.append(dict(kind="IO", T=n))
            continue
        e = ev[k]
        k += 1
        kind = {"F": "OCF", "D": "RD", "R": "RD", "W": "WR", "P": "PR", "Q": "PW"}[t[0]]
        c = dict(kind=kind, T=n, addr=e[1], data=e[2])
        if kind == "OCF":
            c["i"], c["r"] = e[3], e[4]
        out.append(c)
    return out


# ---- pin simulation -------------------------------------------------------------------------------------
def _fmt(v, w):
    return "x" if v is None else format(v, "0%dx" % w)


class PinSim:
    """Runs a RecZ80 and a stimulus source, producing the half-T pin rows.

    `stim` provides: wait() -> 0/1 per T state; t1h(int_n, nmi_n, busrq_n) -> proposed (int_n, nmi_n, busrq_n)
    at a T1H; release() -> True to drop BUSRQ at a Tx rising edge; vec(im) -> byte for an INTA.
    `gen` (optional) provides ensure(cpu) -> bool (False = stop) called before every instruction step, and
    seen(events) after every step.
    Stimulus legality (spec v1 §8.4 item 7): wait changes at rising edges only; int_n, nmi_n and busrq_n change only
    at a T1H (busrq_n also at Tx rising edges, to release); int_n/nmi_n are forced high at the T1H of HALT (SPEC-GAP 3).
    """

    def __init__(self, cpu, stim, gen=None):
        self.cpu, self.stim, self.gen = cpu, stim, gen
        self.rows, self.srows, self.idx = [], [], []
        self.h = 0
        self.halt_n = 1
        self.int_n = self.nmi_n = self.busrq_n = 1
        self.wait_n = 1
        self.reset_n = 0
        self.in_reset = True
        self.vec = 0xFF
        self.nmi_prev = 1            # NMI as sampled at the previous edge (edge detector, §8.4 item 6)
        self.nmi_edges = []          # half indices of edges that became pending and are not yet committed
        self.vis_int = False
        self.vis_nmi = False
        self.sampled = False         # did the last step end in a sampling point?
        self.sample_h = 0
        self.busrq_sampled = False
        self.ctx = dict(final=False, halt=False, sample=False)
        self.cov = {}
        self.stop_reason = "limit"

    def count(self, k, n=1):
        self.cov[k] = self.cov.get(k, 0) + n

    # -- one half T state ------------------------------------------------------------------------------
    def half(self, pins, rising, t1h=False, last=False, tx=False):
        """Emit one half. `rising`: this half starts at a rising edge (H half). `last`: it starts the last T state of an
        M cycle (BUSRQ sample point, and INT/NMI sample point when ctx.sample)."""
        # edge E_h: samples see the values held during the previous half
        nmi_held = self.nmi_n
        if self.nmi_prev == 1 and nmi_held == 0:
            self.nmi_edges.append(self.h)
        self.nmi_prev = nmi_held
        if last:
            self.busrq_sampled = self.busrq_n == 0
            if self.ctx["sample"]:
                self.sample_h = self.h
                # spec v1 §8.4 item 4: BUSRQ sampled 0 at the same edge -> neither INT nor NMI is accepted here;
                # a pending NMI stays pending, INT is sampled again at the next instruction end
                blocked = self.busrq_n == 0
                self.vis_int = self.int_n == 0 and not blocked
                self.vis_nmi = any(e < self.h for e in self.nmi_edges) and not blocked
                if blocked and (self.int_n == 0 or any(e < self.h for e in self.nmi_edges)):
                    self.count("int_or_nmi_blocked_by_busrq")
        if rising and not self.in_reset:
            self.wait_n = self.stim.wait()
        if t1h:
            self._t1h_inputs()
        if tx and self.busrq_n == 0 and self.stim.release():
            self.busrq_n = 1
        p = dict(m1_n=1, mreq_n=1, iorq_n=1, rd_n=1, wr_n=1, rfsh_n=1, halt_n=self.halt_n, busak_n=1, bus_oe=1,
                 d_oe=0, a=None, d_out=None)
        pp = pins() if callable(pins) else pins
        p.update(pp)
        if "halt_n" in pp and pp["halt_n"] is not None:
            self.halt_n = pp["halt_n"]
        if not p["bus_oe"]:
            for k in ("a", "mreq_n", "iorq_n", "rd_n", "wr_n", "rfsh_n"):
                p[k] = None
        if not p["d_oe"]:
            p["d_out"] = None
        self.rows.append((self.h, p))
        self.srows.append((self.h, self.wait_n, self.int_n, self.nmi_n, self.busrq_n, self.reset_n, self.vec))
        self.h += 1

    def power_up(self):
        """§5 item 3a: reset_n low from before half 0, released at half E=8, first T1H at E+2. Nothing is compared in
        halves 0-1; from half 2 m1_n, halt_n, busak_n = 1 and the buses float. Inputs inactive until the first M1."""
        none = dict(a=None, d_out=None, m1_n=None, mreq_n=None, iorq_n=None, rd_n=None, wr_n=None, rfsh_n=None,
                    halt_n=None, busak_n=None, bus_oe=None, d_oe=None)
        E = getattr(self.stim, "reset_release", lambda: POWERUP_E)()
        for k in range(E + 2):
            self.reset_n = 1 if k >= E else 0
            if k < 2:
                self.half(none, k % 2 == 0)
            else:
                self.half(dict(bus_oe=0, d_oe=0, m1_n=1, halt_n=1, busak_n=1), k % 2 == 0)
        self.in_reset = False

    def _t1h_inputs(self):
        want_int, want_nmi, want_br = self.stim.t1h(self.int_n, self.nmi_n, self.busrq_n)
        if self.ctx["halt"]:                       # SPEC-GAP 3
            want_int, want_nmi = 1, 1
        if want_br == 0 and self.busrq_n == 1:
            self.count("busrq_asserted")
        if want_int == 0 and self.int_n == 1:
            self.count("int_asserted")
        if want_nmi == 0 and self.nmi_n == 1:
            self.count("nmi_asserted")
        self.int_n, self.nmi_n, self.busrq_n = want_int, want_nmi, want_br

    # -- M cycle machinery ------------------------------------------------------------------------------
    def run_cycle(self, states, sample_idx=None, wait_row=None, final=False):
        """states: list of (H pins, L pins) per T. After L of states[sample_idx] WAIT is sampled; while it reads 0
        a Tw (wait_row) is inserted. The cycle ends with the BUSRQ sample and, if floated, Tx states."""
        n = len(states)
        for i, (hp, lp) in enumerate(states):
            last = i == n - 1
            self.half(hp, True, t1h=(i == 0), last=last)
            w = self.wait_n
            self.half(lp, False)
            if i == sample_idx:
                while w == 0:
                    self.count("wait_states")
                    self.half(wait_row[0], True)
                    w = self.wait_n
                    self.half(wait_row[1], False)
        if self.busrq_sampled:
            self.bus_grant()

    def bus_grant(self):
        """§4.4: from the next rising edge the CPU floats the buses and drives busak_n low. BUSRQ is sampled at each
        Tx rising edge (the value held in the half before it); BUSRQ may be dropped at any Tx rising edge. Once a
        sample reads 1, busak_n returns to 1 at the falling edge of that Tx, and the next T1 follows."""
        self.count("bus_grants")
        fl = dict(bus_oe=0, d_oe=0)
        while True:
            high = self.busrq_n == 1
            self.half(dict(fl, busak_n=0), True, tx=True)
            self.half(dict(fl, busak_n=1 if high else 0), False)
            if high:
                break
        self.busrq_sampled = False

    # -- cycle builders (§4.1-4.5) ---------------------------------------------------------------------------
    def _idle(self, n):
        return [({"a": None}, {"a": None}) for _ in range(n)]

    def c_ocf(self, a, i, r, extra, final, halt=None, dummy=False):
        """§4.1. halt: None, 'fall' (HALT's own M1), 'hold', or 'accept' (decided at T4H)."""
        ra = (i << 8) | r
        f = dict(a=a, m1_n=0)
        rd = dict(f, mreq_n=0, rd_n=0)
        rf = dict(a=ra, rfsh_n=0)
        def t4l():
            hp = {}
            if halt == "fall":
                hp = dict(halt_n=0)
            elif halt == "accept":
                hp = dict(halt_n=1) if (self.vis_nmi or (self.vis_int and self.cpu.iff1)) else {}
            return dict(rf, mreq_n=1, **hp)
        st = [(f, rd), (rd, rd), (dict(rf), dict(rf, mreq_n=0)), (dict(rf, mreq_n=0), t4l)]
        st += self._idle(extra)
        self.run_cycle(st, sample_idx=1, wait_row=(rd, rd), final=final)

    def c_mem(self, kind, a, data, extra, final):
        """§4.2: read or write, 3 T plus extra internal T (strobes inactive, `a` not compared, §6.1 lengthened rule)."""
        if kind == "RD":
            h1, l1 = dict(a=a), dict(a=a, mreq_n=0, rd_n=0)
            h2 = l2 = h3 = l1
            l3 = dict(a=a)
        else:
            d = dict(d_oe=1, d_out=data)
            h1, l1 = dict(a=a), dict(a=a, mreq_n=0, **d)
            h2, l2 = dict(l1), dict(l1, wr_n=0)
            h3, l3 = dict(l2), dict(a=a, **d)
        st = [(h1, l1), (h2, l2), (h3, l3)] + self._idle(extra)
        self.run_cycle(st, sample_idx=1, wait_row=(l2, l2), final=final)   # Tw repeats the T2L row (spec v1 §4.2)

    def c_io(self, kind, a, data, final):
        """§4.3: T1, T2, Tw*, T3; WAIT sampled at Tw*L, more Tw while it reads 0."""
        w = kind == "PW"
        d = dict(d_oe=1, d_out=data) if w else {}
        stb = dict(wr_n=0) if w else dict(rd_n=0)
        t1h, t1l = dict(a=a), dict(a=a, **d)
        act = dict(a=a, iorq_n=0, **stb, **d)
        t3l = dict(a=a, **d)
        self.run_cycle([(t1h, t1l), (act, act), (act, act), (act, t3l)], sample_idx=2, wait_row=(act, act), final=final)

    def c_idle(self, n, final):
        self.run_cycle(self._idle(n), final=final)

    def c_inta(self, a, i, r, T, final):
        """§4.5: T1, T2, Tw*, Tw*, T3, T4 (+T5 in modes 1/2, SPEC: 7 T, extra T after T4)."""
        ra = (i << 8) | r
        f = dict(a=a, m1_n=0)
        io = dict(f, iorq_n=0)
        rf = dict(a=ra, rfsh_n=0)
        st = [(f, f), (f, f), (f, io), (io, io),
              (dict(rf), dict(rf, mreq_n=0)), (dict(rf, mreq_n=0), dict(rf))]
        st += self._idle(T - 6)
        self.run_cycle(st, sample_idx=3, wait_row=(io, io), final=final)

    def emit(self, c, final):
        k = c["kind"]
        if k == "OCF":
            self.c_ocf(c["pc"] if "pc" in c else c["addr"], c["i"], c["r"], c["T"] - 4, final,
                       halt=c.get("halt"))
        elif k in ("RD", "WR"):
            self.c_mem(k, c["addr"], c["data"], c["T"] - 3, final)
        elif k in ("PR", "PW"):
            self.c_io(k, c["addr"], c["data"], final)
        elif k == "IO":
            self.c_idle(c["T"], final)
        elif k == "INTA":
            self.c_inta(c["addr"], c["i"], c["r"], c["T"], final)
        else:
            raise AssertionError(k)

    # -- step driver ------------------------------------------------------------------------------------
    def run(self, max_steps):
        cpu = self.cpu
        if self.h == 0:
            self.power_up()
        for n in range(max_steps):
            if self.sampled:
                cpu.int_line = self.vis_int
                cpu.nmi_pending = bool(self.vis_nmi)
            else:
                cpu.int_line = False
                cpu.nmi_pending = False
            nmi_taking = cpu.nmi_pending
            int_taking = (not nmi_taking) and cpu.int_line and cpu.iff1 and not cpu.ei_delay
            if cpu.int_line and not int_taking and not nmi_taking:
                self.count("int_seen_not_taken_ei_delay" if (cpu.iff1 and cpu.ei_delay) else "int_seen_masked")
            response = nmi_taking or int_taking
            was_halted = cpu.halted
            if self.gen is not None and not response and not cpu.halted:
                if not self.gen.ensure(cpu):
                    self.stop_reason = "dead-end"
                    break
            vec = self.stim.vec(cpu.im) if int_taking else None
            if vec is not None:
                cpu.int_data = lambda v=vec: v
            pc0 = cpu.pc
            cpu.events = []
            try:
                T = cpu.step()
            except (Undocumented, Unspecified) as e:
                self.stop_reason = "model-raised: %s" % e
                break
            ev, kind = cpu.events, cpu.last
            self.idx.append((self.h, pc0, kind if kind == "NMI" or kind == "HALT-M1" or kind.startswith("INT") else "I " + kind))
            if self.gen is not None:
                self.gen.seen(ev)
            if kind == "NMI":                       # commit: edges visible at the sampling point are consumed
                self.nmi_edges = [e for e in self.nmi_edges if e >= self.sample_h]
            if self.emit_step(kind, ev, T, vec, was_halted):
                self.stop_reason = "undetermined"
                break
        return self

    def emit_step(self, kind, ev, T, vec, was_halted):
        cpu = self.cpu
        sample = True
        if kind == "NMI" or kind.startswith("INT"):
            sample = False
            e = _evs(ev)
            m1 = e[0]
            if kind == "NMI":
                self.count("nmi_taken")
                cyc = [dict(kind="OCF", T=5, addr=m1[1], i=m1[3], r=m1[4])]
                if was_halted:
                    self.count("nmi_while_halted")
            else:
                mode = int(kind[3])
                self.count("int_taken_mode%d" % mode)
                if was_halted:
                    self.count("int_while_halted")
                cyc = [dict(kind="INTA", T=6 if mode == 0 else 7, addr=m1[1], i=m1[3], r=m1[4])]
                self.vec = vec
            for x in e[1:]:
                cyc.append(dict(kind={"MW": "WR", "MR": "RD"}[x[0]], T=3, addr=x[1], data=x[2]))
        elif kind == "HALT-M1":
            m1 = _evs(ev)[0]
            cyc = [dict(kind="OCF", T=4, addr=m1[1], i=m1[3], r=m1[4], halt="accept")]
            self.count("halted_m1")
        else:
            tk, swap = tokens(ev, T)
            cyc = cycles_from_tokens(tk, ev, swap)
            if cpu.halted:                          # HALT itself: halt_n falls at T4L
                cyc[0]["halt"] = "fall"
                self.count("halt_executed")
        halt_instr = cpu.halted and kind != "HALT-M1" and kind != "NMI" and not kind.startswith("INT")
        for j, c in enumerate(cyc):
            self.ctx = dict(sample=sample, halt=halt_instr, final=j == len(cyc) - 1)
            self.emit(c, j == len(cyc) - 1)
        self.sampled = sample
        # SPEC-GAP 3: an interrupt visible at the end of HALT's own M1 has no defined halt_n; stop the run
        if halt_instr and (self.vis_nmi or (self.vis_int and cpu.iff1)):
            self.count("undetermined_halt_end")
            return True
        return False

    # -- output ---------------------------------------------------------------------------------------------
    def write(self, base):
        """base.pins (expected trace, tb TRACE layout), base.stim, base.idx."""
        with open(base + ".pins", "w") as f:
            f.write("# z80-pintrace v2: one row per half T state, the layout z80_system dumps with +TRACE=; x = not compared\n")
            f.write("half a d_out d_oe m1_n mreq_n iorq_n rd_n wr_n rfsh_n halt_n busak_n bus_oe | "
                    "wait_n int_n nmi_n busrq_n reset_n d_in\n")
            for (h, p), sr in zip(self.rows, self.srows):
                f.write("%d %s %s %s %s %s %s %s %s %s %s %s %s | %d %d %d %d %d x\n" % (
                    (h, _fmt(p["a"], 4), _fmt(p["d_out"], 2)) + tuple(_fmt(p[k], 1) for k in (
                        "d_oe", "m1_n", "mreq_n", "iorq_n", "rd_n", "wr_n", "rfsh_n", "halt_n", "busak_n", "bus_oe")) + sr[1:6]))
        with open(base + ".stim", "w") as f:
            f.write("# z80-stim v2: inputs held during each half; vec = byte on d_in during an INTA\n")
            f.write("half " + " ".join(STIM_COLS) + "\n")
            for r in self.srows:
                f.write("%d %d %d %d %d %d %02x\n" % r)
        with open(base + ".idx", "w") as f:
            f.write("# half_start pc kind/bytes\n")
            for t, pc, k in self.idx:
                f.write("%d %04x %s\n" % (t, pc, k))

    def write_vectors(self, d, name, image):
        """The files z80_system reads for one case (packing as in tb/z80_bus/tb.sv), plus vec.hex (INTA data per half,
        needs the tb extension described in tests/random/README.md) and a cases.txt line `name halves events`."""
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "prog.hex"), "w") as f:
            f.write("@0000\n")
            for a in range(0, 65536, 16):
                f.write(" ".join("%02X" % b for b in image[a:a + 16]) + "\n")
        ev = []
        prev = None
        for sr in self.srows:
            cur = sr[1:6]
            if cur != prev and not (prev is None and cur == (1, 1, 1, 1, 0)):
                ev.append((sr[0],) + cur)
            prev = cur
        with open(os.path.join(d, "stim.hex"), "w") as f:
            for h, w, i, n, b, r in ev:
                f.write("%08X\n" % (h << 8 | r << 4 | n << 3 | i << 2 | b << 1 | w))
        with open(os.path.join(d, "inp.hex"), "w") as f:
            for sr in self.srows:
                f.write("%02X\n" % (sr[5] << 4 | sr[3] << 3 | sr[2] << 2 | sr[4] << 1 | sr[1]))
        with open(os.path.join(d, "vec.hex"), "w") as f:
            for sr in self.srows:
                f.write("%02X\n" % sr[6])
        with open(os.path.join(d, "exp.hex"), "w") as fe, open(os.path.join(d, "mask.hex"), "w") as fm:
            for h, p in self.rows:
                v = m = 0
                if p["a"] is not None:
                    v |= p["a"] << 20; m |= 0xFFFF << 20
                if p["d_out"] is not None:
                    v |= p["d_out"] << 12; m |= 0xFF << 12
                for bit, k in ((11, "m1_n"), (10, "mreq_n"), (9, "iorq_n"), (8, "rd_n"), (7, "wr_n"), (6, "rfsh_n"),
                               (5, "halt_n"), (4, "busak_n"), (3, "bus_oe"), (2, "d_oe")):
                    if p[k] is not None:
                        v |= p[k] << bit; m |= 1 << bit
                fe.write("%09X\n" % v)
                fm.write("%09X\n" % m)
        return "%s %d %d" % (name, len(self.rows), len(ev))
