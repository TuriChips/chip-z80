#!/usr/bin/env python3
"""Equivalence + speed: old bench (sw/exerciser/z80_acc_tb.sv, build/acc/obj) vs fast driver (make acc-fast-build) on prelim and zexdoc groups.
Usage: scripts/acc_equiv.py LOG [group ...]   (run `python3 -I sw/exerciser/run_rtl.py build` and `make acc-fast-build` first; use `heavy`)
Compares program output and the [acc] line (done, timeout, half-clocks; bus_conflict is shown, not compared: the bench prints the last cycle, the driver is sticky).
Uses run_rtl.py read-only (hexfile, zex_table, fetch). Owner: Tesla."""
import importlib.util, os, re, subprocess, sys, time
spec = importlib.util.spec_from_file_location("run_rtl", "sw/exerciser/run_rtl.py")
rr = importlib.util.module_from_spec(spec); spec.loader.exec_module(rr)
NEW = "build/acc-fast/obj/Vz80_system"

def run(binp, hexf):
    t = time.time()
    out = subprocess.run([binp, f"+hex={hexf}", f"+maxclk={os.environ.get('ACC_MAXCLK', 4000000000)}"], capture_output=True, text=True).stdout
    return out, time.time() - t

def split(out):
    prog, _, tail = out.partition("[acc]")
    return prog, rr.acc_line("[acc]" + tail)

log = open(sys.argv[1], "w")
def w(s): print(s, flush=True); log.write(s + "\n"); log.flush()
w(f"# old bench vs fast driver, {rr.tool_line()}, rtl commit {subprocess.check_output(['git','rev-parse','--short','HEAD'],text=True).strip()}, {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
jobs = [("prelim", rr.hexfile("prelim", open(rr.fetch("prelim"), "rb").read()))]
zc = open(rr.fetch("zexdoc"), "rb").read(); tbl, ptrs = rr.zex_table(zc)
for g in map(int, sys.argv[2:]):
    jobs.append((f"zexdoc-{g}", rr.hexfile(f"zexdoc-{g}", zc, {tbl: ptrs[g] & 255, tbl + 1: ptrs[g] >> 8, tbl + 2: 0, tbl + 3: 0})))
allok = True
for name, hexf in jobs:
    (oo, to), (no, tn) = run(rr.BIN, hexf), run(NEW, hexf)
    (po, ao), (pn, an) = split(oo), split(no)
    same = po == pn and ao and an and ao[:2] == an[:2] and ao[3] == an[3]
    allok &= bool(same)
    hc = an[3] if an else 0
    w(f"{name}: {'IDENTICAL' if same else 'DIFFERENT'} output ({len(po)} chars) and half-clocks; old [done,timeout,conflict,hc]={ao} new={an}")
    w(f"  old {to:.1f}s = {hc/to:,.0f} half-clocks/s; new {tn:.1f}s = {hc/tn:,.0f} half-clocks/s; speedup {to/tn:.1f}x")
    if not same:
        w("  old out: " + repr(po[-300:])); w("  new out: " + repr(pn[-300:]))
w("# RESULT " + ("PASS" if allok else "FAIL"))
sys.exit(0 if allok else 1)
