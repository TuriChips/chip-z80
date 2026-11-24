#!/usr/bin/env python3
"""Runs sw/demo/demo.com on the RTL and on the reference model, compares, writes logs. Owner: Homer.
Reuses sw/exerciser/run_rtl.py (same z80_system CPM=1 bench, same hexfile/sim helpers); nothing is forked.
Usage: sw/demo/run_demo.py     # writes logs/demo-rtl.log and logs/demo-ref.log; exit 0 only if identical and finished
"""
import importlib.util, os, subprocess, sys

spec = importlib.util.spec_from_file_location("run_rtl", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "exerciser", "run_rtl.py"))
rr = importlib.util.module_from_spec(spec); spec.loader.exec_module(rr)   # chdirs to the repo root

COM = "sw/demo/demo.com"
com = open(COM, "rb").read()
os.makedirs("build/acc", exist_ok=True)
if not os.path.exists(rr.BIN):
    rr.build()
out, dt = rr.sim(rr.hexfile("demo", com), 4_000_000_000)
a = rr.acc_line(out)
rtl_text = out.split("[acc]")[0].replace("\r", "").rstrip("\n") + "\n"
ref = subprocess.run([sys.executable, "-I", "sw/cpm_ref.py", COM, "--x6", "mostek", "--daa", "nmos"], capture_output=True, text=True).stdout
ref_text = "".join(l + "\n" for l in ref.splitlines() if not l.startswith("#")).rstrip("\n") + "\n"
same = rtl_text == ref_text
ok = bool(a) and a[0] == 1 and a[2] == 0 and same
os.makedirs("logs", exist_ok=True)
with open("logs/demo-rtl.log", "w") as f:
    f.write(rr.header("demo", COM, []).replace("(pinned by sw/exerciser/fetch.sh)", "(built by sw/demo/build_demo.py)"))
    f.write(f"# [acc] done={a[0]} timeout={a[1]} bus_conflict={a[2]} half-T-clocks={a[3]}\n" if a else "# no [acc] line\n")
    f.write(rtl_text)
    f.write(f"# RESULT {'PASS' if ok else 'FAIL'}: console output {'byte-identical to' if same else 'DIFFERENT from'} sw/cpm_ref.py (--x6 mostek --daa nmos), {dt:.1f}s wall\n")
with open("logs/demo-ref.log", "w") as f:
    f.write(f"# demo.com on sw/cpm_ref.py --x6 mostek --daa nmos, rtl commit {subprocess.check_output(['git','rev-parse','--short','HEAD'],text=True).strip()}\n")
    f.write(ref_text)
print(open("logs/demo-rtl.log").read())
sys.exit(0 if ok else 1)
