#!/usr/bin/env python3
"""Cross-check of rtl/control/z80_decode.v against the pin model (Beru, chip-z80#39).

Independent of rtl/control/gen_decode.py and its table: the committed z80_decode.v is simulated (Verilator) over all
2048 {prefix, ir}, and for every specified form (refz80.census(), 850) the M-cycle (type, len) sequence of every outcome the
reference model produces (cc met / not met, DJNZ B=1/2, BC=1/2 repeats, CPIR match / no match: 5 F x 3 A x 5 BC states)
is read from ref/pinsz80.tokens() and must equal the RTL plan[:pn] or plan[:pn_s] (s3 sets M3 to length 3).
Also: `specified` == the census, `is_prefix` == exactly the six prefix bytes and never specified, plan slots past pn
are zero. A DIFF is a finding for Zura (RTL) or for whoever is wrong; never patch it here.

  python3 -I -B tests/random/xcheck_decode.py          (needs verilator; prints PASS / FAIL and DIFF lines)
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
sys.path.insert(0, os.path.join(ROOT, "ref"))
import refz80  # noqa: E402
import pinsz80  # noqa: E402

TY = {"F": 0, "D": 1, "R": 1, "W": 2, "P": 3, "Q": 4, "I": 5}  # token letter -> mc_type code (blocks.md section 3)
PREFIX_BYTES = {(0, 0xCB), (0, 0xDD), (0, 0xED), (0, 0xFD), (2, 0xCB), (4, 0xCB)}
SEQS = {0: lambda o: [o], 1: lambda o: [0xCB, o], 2: lambda o: [0xDD, o, 5, 7], 3: lambda o: [0xED, o],
        4: lambda o: [0xFD, o, 5, 7], 5: lambda o: [0xDD, 0xCB, 5, o], 6: lambda o: [0xFD, 0xCB, 5, o]}


def simulate():
    d = tempfile.mkdtemp(prefix="xdecode.")
    r = subprocess.run(["verilator", "--binary", "--timing", "-Wno-fatal", "--top-module", "decode_tb", "-Mdir", d,
                        "-o", "sim", os.path.join(HERE, "decode_tb.v"),
                        os.path.join(ROOT, "rtl", "control", "z80_decode.v")], capture_output=True, text=True)
    if r.returncode:
        print("FAIL verilator build\n" + r.stdout + r.stderr)
        sys.exit(1)
    out = subprocess.run([os.path.join(d, "sim")], capture_output=True, text=True).stdout
    rtl = {}
    for l in out.splitlines():
        f = l.split()
        if len(f) != 10:
            continue
        pr, ir, dd, p, ins, pn, pns, s3, pt, pl = f
        pt, pl = int(pt, 8), int(pl, 8)
        rtl[(int(pr), int(ir))] = dict(d=int(dd), p=int(p), pn=int(pn), pns=int(pns), s3=int(s3),
                                       plan=[((pt >> 3 * k) & 7, (pl >> 3 * k) & 7) for k in range(6)])
    if len(rtl) != 2048:
        print("FAIL simulation produced %d of 2048 rows (an X or a build problem?)\n%s" % (len(rtl), out[:500]))
        sys.exit(1)
    return rtl


def census_keys():
    fs, _ = refz80.census()
    cen = set()
    for f in fs:
        if f[0] == "main":
            cen.add((0, f[1]))
        elif len(f) == 3:
            cen.add(({"DD": 5, "FD": 6}[f[0]], f[2]))
        else:
            cen.add(({"CB": 1, "DD": 2, "ED": 3, "FD": 4}[f[0]], f[1]))
    return cen


def ref_layouts(k):
    got = set()
    for F in (0x00, 0xFF, 0x44, 0x04, 0x40):
        for A in (0, 1, 0x80):
            for BC in (0x0000, 0x0001, 0x0102, 0x0201, 0x0100):
                c = pinsz80.RecZ80(refz80.Policy("taint", "taint"))
                c.pc, c.sp = 0x100, 0x8000
                seq = SEQS[k[0]](k[1])
                c.mem[0x100:0x100 + len(seq)] = bytes(seq + [0, 0, 0])
                c.f, c.a = F, A
                c.reg[0], c.reg[1] = BC >> 8, BC & 255
                c.set_rp(2, 0x200)
                c.ix = c.iy = 0x200
                c.events = []
                try:
                    T = c.step()
                except refz80.Unspecified:
                    continue
                tk, _ = pinsz80.tokens(c.events, T)
                got.add(tuple((TY[t[0]], int(t[1:])) for t in tk))
    return got


def main():
    rtl = simulate()
    cen = census_keys()
    bad = 0
    doc = {k for k, v in rtl.items() if v["d"]}
    if doc != cen:
        bad += 1
        print("DIFF specified != census: extra %s missing %s" % (sorted(doc - cen)[:10], sorted(cen - doc)[:10]))
    pre = {k for k, v in rtl.items() if v["p"]}
    if pre != PREFIX_BYTES:
        bad += 1
        print("DIFF is_prefix set %s, want %s" % (sorted(pre), sorted(PREFIX_BYTES)))
    if pre & doc:
        bad += 1
        print("DIFF is_prefix overlaps specified: %s" % sorted(pre & doc))
    for k in sorted(cen):
        r = rtl[k]
        if any(c != (0, 0) for c in r["plan"][r["pn"]:]):
            bad += 1
            print("DIFF %s plan slots past pn not zero: %s" % (k, r["plan"]))
        full = r["plan"][:r["pn"]]
        short = [list(c) for c in r["plan"][:r["pns"]]]
        if r["s3"]:
            short[2][1] = 3
        want = {tuple(full), tuple(tuple(c) for c in short)}
        got = ref_layouts(k)
        if got != want:
            bad += 1
            print("DIFF %s rtl %s ref %s" % (k, sorted(want), sorted(got)))
    print("forms %d, specified %d, mismatches %d" % (len(cen), len(doc), bad))
    print("PASS" if bad == 0 else "FAIL")
    sys.exit(1 if bad else 0)


main()
