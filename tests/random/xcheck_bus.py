#!/usr/bin/env python3
"""Cross-check of the pin model against Titus's directed bus-cycle vectors (Beru, chip-z80#8; Titus's PR #12).

Two implementations written from the same spec by different people: ref/pinsz80.py (Beru) and tests/z80_bus/zbus.py
(Titus). For every case in tests/z80_bus/vectors/cases.txt that fits (no reset after power-up, no memory banks) the
model replays that case's prog.hex and stim.hex and its exp/mask words are compared with Titus's, under Titus's mask.
A DIFF is a finding for Igris (spec) or for whoever is wrong, never something to patch over here.

  python3 tests/random/xcheck_bus.py [vectors_dir]      (skips with SKIP if the vectors are not in the tree yet)
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
sys.path.insert(0, os.path.join(ROOT, "ref"))
sys.path.insert(0, HERE)
from refz80 import Policy  # noqa: E402
from pinsz80 import RecZ80, PinSim  # noqa: E402
import refrun  # noqa: E402


def words(path):
    return [l.strip() for l in open(path) if l.strip() and not l.startswith("@")]


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "tests", "z80_bus", "vectors")
    if not os.path.exists(os.path.join(d, "cases.txt")):
        print("SKIP xcheck_bus: %s/cases.txt not found (Titus's vectors, chip-z80 PR #12)" % d)
        return 0
    bad = ok = skip = 0
    for line in open(os.path.join(d, "cases.txt")):
        name, nh, nev = line.split()
        nh = int(nh)
        cd = os.path.join(d, name)
        evs = [int(x, 16) for x in words(os.path.join(cd, "stim.hex"))]
        cur, rows, ei = (1, 1, 1, 1, 0), [], 0
        vp = os.path.join(cd, "vec.hex")     # INTA byte per half, written only when not FFH (C4-09..12)
        vecs = [int(x, 16) for x in words(vp)] if os.path.exists(vp) else []
        for h in range(nh + 300):
            if ei < len(evs) and evs[ei] >> 8 == h:
                w = evs[ei]
                cur = (w & 1, (w >> 2) & 1, (w >> 3) & 1, (w >> 1) & 1, (w >> 4) & 1)   # wait int nmi busrq reset
                ei += 1
            rows.append((h,) + cur + (vecs[h] if h < len(vecs) else 0xFF,))
        if os.path.exists(os.path.join(cd, "prog1.hex")) or any(r[5] == 0 for r in rows[10:nh]):
            print("SKIP %s (reset after power-up or memory banks)" % name)
            skip += 1
            continue
        mem, addr = bytearray(65536), 0
        for l in open(os.path.join(cd, "prog.hex")):
            l = l.strip()
            if l.startswith("@"):
                addr = int(l[1:], 16)
                continue
            for b in l.split():
                mem[addr] = int(b, 16)
                addr += 1
        cpu = RecZ80(Policy())
        cpu.mem[:] = mem
        st = refrun.ReplayStim(rows)
        sim = PinSim(cpu, st)
        st.sim = sim
        while sim.h < nh and sim.stop_reason == "limit":
            sim.run(1)
        with tempfile.TemporaryDirectory() as t:
            sim.write_vectors(t, "x", bytes(mem))
            mine = [int(x, 16) for x in words(os.path.join(t, "exp.hex"))]
            mm = [int(x, 16) for x in words(os.path.join(t, "mask.hex"))]
        exp = [int(x, 16) for x in words(os.path.join(cd, "exp.hex"))]
        msk = [int(x, 16) for x in words(os.path.join(cd, "mask.hex"))]
        if len(mine) < nh:
            bad += 1
            print("DIFF %s: model made only %d of %d halves (stopped: %s)" % (name, len(mine), nh, sim.stop_reason))
            continue
        diff = [h for h in range(nh) if (mine[h] ^ exp[h]) & msk[h] or msk[h] & ~mm[h]]
        if diff or sim.h < nh:
            bad += 1
            h = diff[0] if diff else sim.h
            print("DIFF %s: %d halves differ, first at half %d: model %09X/%09X Titus %09X/%09X"
                  % (name, len(diff), h, mine[h], mm[h], exp[h], msk[h]))
        else:
            ok += 1
            print("ok   %s (%d halves)" % (name, nh))
    print("%s xcheck_bus: %d agree, %d differ, %d skipped" % ("FAIL" if bad else "PASS", ok, bad, skip))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
