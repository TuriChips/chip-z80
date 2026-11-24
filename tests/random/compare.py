#!/usr/bin/env python3
"""Diff two per-half-T pin traces (Beru, chip-z80#8). Spec §4.0: every pin is compared in every half.

  python3 tests/random/compare.py EXPECTED.pins ACTUAL.pins [--idx EXPECTED.idx] [--all N]

Format (ref/pinsz80.py writes it, and z80_system dumps the same with +TRACE=<prefix>, chip-z80#12): `#` comment lines,
a header line `half a d_out d_oe m1_n ... bus_oe | wait_n int_n nmi_n busrq_n reset_n d_in` naming the columns (any
order; the `|` and the input columns after it are ignored, missing pin columns are an error), then one row per half
T state, half 0 = first rising edge (power-up reset included); a and d_out in hex, the rest bits. In EXPECTED, `x` means "not compared"
(floating pins while bus_oe=0, `a` in internal T states, d_out while d_oe=0, §4.4 and §6.1). In ACTUAL an `x` or
`z` (4-state simulators) in a pin that EXPECTED defines is a difference.
Reports the first difference: half index, T state within the instruction, pin, both values, the instruction in
flight (from the .idx). Exit 0 and a PASS line if none, else FAIL + exit 1.
"""
import argparse
import sys

PINS = ["a", "m1_n", "mreq_n", "iorq_n", "rd_n", "wr_n", "rfsh_n", "halt_n", "busak_n", "bus_oe", "d_oe", "d_out"]


def load(path):
    cols, rows = None, []
    with open(path) as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            w = [x for x in ln.split() if x != "|"]
            if cols is None:
                if w[0] not in ("t", "half"):
                    sys.exit("%s: first non-comment line must be the header `half ...`" % path)
                cols = ["t"] + w[1:]
                continue
            rows.append(dict(zip(cols, w)))
    if cols is None:
        sys.exit("%s: no header" % path)
    missing = [p for p in PINS if p not in cols]
    return cols, rows, missing


def load_idx(path):
    out = []
    with open(path) as f:
        for ln in f:
            if ln.startswith("#") or not ln.strip():
                continue
            t, pc, rest = ln.split(None, 2)
            out.append((int(t), int(pc, 16), rest.strip()))
    return out


def same(e, a):
    if e == "x":
        return True
    if a.lower() in ("x", "z") or "x" in a.lower() or "z" in a.lower():
        return False
    try:
        return int(e, 16) == int(a, 16)
    except ValueError:
        return e == a


def inflight(idx, t):
    cur = None
    for e in idx:
        if e[0] <= t:
            cur = e
        else:
            break
    return cur


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("expected")
    ap.add_argument("actual")
    ap.add_argument("--idx")
    ap.add_argument("--all", type=int, default=1, help="report the first N differences (default 1)")
    a = ap.parse_args()
    ec, er, em = load(a.expected)
    ac, ar, am = load(a.actual)
    if am:
        sys.exit("FAIL: %s lacks columns %s" % (a.actual, am))
    idx = load_idx(a.idx) if a.idx else []
    nd = 0
    for k, e in enumerate(er):
        if k >= len(ar):
            print("FAIL: actual trace ends at half %d, expected has %d halves" % (k, len(er)))
            return 1
        r = ar[k]
        if int(r["t"]) != int(e["t"]):
            print("FAIL: row %d: actual t=%s, expected t=%s" % (k, r["t"], e["t"]))
            return 1
        for p in PINS:
            if p == "d_out" and e.get("d_oe") == "0":
                continue
            if not same(e[p], r[p]):
                nd += 1
                t = int(e["t"])
                ins = inflight(idx, t)
                where = ""
                if ins:
                    where = "  in flight: %s at pc=%04x (starts at half %d, +%d halves)" % (ins[2], ins[1], ins[0], t - ins[0])
                print("DIFF half %d pin %s: expected %s, got %s%s" % (t, p, e[p], r[p], where))
                if nd >= a.all:
                    print("FAIL: %d difference(s) shown (first at half %s)" % (nd, e["t"]))
                    return 1
                break
    if len(ar) > len(er):
        print("FAIL: actual trace has %d halves, expected %d" % (len(ar), len(er)))
        return 1
    if nd:
        print("FAIL: %d difference(s)" % nd)
        return 1
    print("PASS %d halves compared, 0 differences" % len(er))
    return 0


if __name__ == "__main__":
    sys.exit(main())
