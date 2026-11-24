#!/usr/bin/env python3
"""Reference model as a device under test (Beru, chip-z80#8): replays a .hex image and a .stim input trace open-loop,
exactly as the RTL testbench does, and writes the pin trace in the .pins format. run.sh uses it until RTL exists.

  python3 tests/random/refrun.py --hex s1.hex --stim s1.stim --out s1.dut   (writes s1.dut.pins)
The generator run and this replay share no state except the two files, so a match proves the image and the stimulus
alone determine the trace (the property the RTL run relies on).
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "ref"))
from refz80 import Policy  # noqa: E402
from pinsz80 import RecZ80, PinSim  # noqa: E402


class ReplayStim:
    def __init__(self, rows):
        self.rows, self.sim = rows, None

    def row(self):
        return self.rows[self.sim.h]

    def reset_release(self): return next(r[0] for r in self.rows if r[5] == 1)
    def wait(self): return self.row()[1]
    def t1h(self, i, n, b): r = self.row(); return r[2], r[3], r[4]
    def release(self): return self.row()[4] == 1
    def vec(self, im): return self.row()[6]


def load_stim(path):
    rows = []
    with open(path) as f:
        for ln in f:
            if ln.startswith("#") or ln.startswith("half "):
                continue
            w = ln.split()
            rows.append((int(w[0]), int(w[1]), int(w[2]), int(w[3]), int(w[4]), int(w[5]), int(w[6], 16)))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hex", required=True)
    ap.add_argument("--stim", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    cpu = RecZ80(Policy())
    cpu.mem[:] = bytes(int(x, 16) for x in open(a.hex).read().split())
    st = ReplayStim(load_stim(a.stim))
    sim = PinSim(cpu, st)
    st.sim = sim
    n = len(st.rows)
    while sim.h < n and sim.stop_reason == "limit":
        sim.run(1)
    sim.write(a.out)
    if sim.h != n:
        sys.exit("FAIL: replay ended at half %d, stimulus has %d" % (sim.h, n))
    print("replayed %d halves" % sim.h)


if __name__ == "__main__":
    main()
