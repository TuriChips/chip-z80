#!/usr/bin/env python3
"""Acceptance runner: prelim and zexdoc on the RTL (z80_system CPM=1, Verilator). Spec §9 item 1. Owner: Homer.

Usage: sw/exerciser/run_rtl.py build                 # verilator build into build/acc/obj
       sw/exerciser/run_rtl.py prelim [LOG]          # default logs/acc-rtl/prelim.log
       sw/exerciser/run_rtl.py zexdoc [LOG] [--groups N,N,..] [--jobs J] [--maxclk HALFCLOCKS]
zexdoc is run one group per simulation (like sw/cpm_ref.py --groups): the test table is patched to hold one group.
Binaries come from sw/exerciser/fetch.sh (pinned commit + sha256, never committed).
Exit 0 only if every group printed OK and finished (done=1, bus_conflict=0).
"""
import argparse, concurrent.futures as cf, hashlib, os, re, subprocess, sys, time

ROOT = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
os.chdir(ROOT)
OBJ = "build/acc/obj"
BIN = f"{OBJ}/Vz80_acc_tb"
RTL = ["rtl/datapath/z80_alu.v", "rtl/datapath/z80_regs.v", "rtl/control/z80_timing.v", "rtl/control/z80_decode.v",
       "rtl/control/z80_control.v", "rtl/top.v", "rtl/datapath/z80_mem.v", "rtl/control/z80_system.v",
       "sw/exerciser/z80_acc_tb.sv"]
# groups that execute undocumented opcodes (decision 9; need U1-U3: chip-z80 #51 ref, #52 Ada SLL, #53 Zura decode)
DECISION9 = {6, 28, 29, 30, 31, 48, 50, 59, 60}


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def build():
    os.makedirs(OBJ, exist_ok=True)
    subprocess.check_call(["verilator", "--binary", "--timing", "-Wno-fatal", "-O3", "--x-assign", "fast", "--x-initial", "fast", "-CFLAGS", "-O3 -march=native", "-j", "2", "-Irtl/control",
                           "--top-module", "z80_acc_tb", "-Mdir", OBJ] + RTL, stdout=subprocess.DEVNULL)


def hexfile(name, com, patch=None):
    mem = {0x100 + i: b for i, b in enumerate(com)}
    if patch:
        mem.update(patch)
    p = f"build/acc/{name}.hex"
    with open(p, "w") as f:
        for a in sorted(mem):
            f.write(f"@{a:04x}\n{mem[a]:02x}\n")
    return p


def sim(hexf, maxclk):
    t0 = time.time()
    r = subprocess.run([BIN, f"+hex={hexf}", f"+maxclk={maxclk}"], capture_output=True, text=True)
    return r.stdout, time.time() - t0


def acc_line(out):
    m = re.search(r"\[acc\] done=(\d) timeout=(\d) bus_conflict=(\d) half-T-clocks=(\d+)", out)
    return m and tuple(int(x) for x in m.groups())


def tool_line():
    return subprocess.check_output(["verilator", "--version"], text=True).strip()


def header(what, com_path, extra):
    h = [f"# {what} on the RTL: z80_system CPM=1 under {tool_line()}, bench sw/exerciser/z80_acc_tb.sv, runner sw/exerciser/run_rtl.py",
         f"# rtl commit {subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], text=True).strip()}, run {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
         f"# {os.path.basename(com_path)} sha256 {sha(com_path)} (pinned by sw/exerciser/fetch.sh)"]
    return "\n".join(h + extra) + "\n"


def prelim(log):
    com = open(fetch("prelim"), "rb").read()
    out, dt = sim(hexfile("prelim", com), 4_000_000_000)
    a = acc_line(out)
    ok = bool(a) and a[0] == 1 and a[2] == 0 and "Preliminary tests complete" in out
    os.makedirs(os.path.dirname(log), exist_ok=True)
    with open(log, "w") as f:
        f.write(header("prelim", "build/third_party/prelim.com", []))
        f.write("\n".join(l for l in out.strip().splitlines() if not l.startswith("- ")) + f"\n# RESULT {'PASS' if ok else 'FAIL'} ({dt:.1f}s wall)\n")
    print(open(log).read())
    return 0 if ok else 1


def fetch(which):
    return subprocess.check_output(["sw/exerciser/fetch.sh", which], text=True).strip().splitlines()[-1]


def zex_table(com):
    i = bytes(com).find(bytes([0x7E, 0x23, 0xB6, 0xCA]))
    assert i >= 3 and com[i - 3] == 0x21, "not a zexdoc .com (test table not found)"
    tbl = com[i - 2] | com[i - 1] << 8
    ptrs = []
    while True:
        k = tbl - 0x100 + 2 * len(ptrs)
        p = com[k] | com[k + 1] << 8
        if not p:
            return tbl, ptrs
        ptrs.append(p)


def one_group(args):
    g, name, com, tbl, ptr, maxclk = args
    patch = {tbl: ptr & 255, tbl + 1: ptr >> 8, tbl + 2: 0, tbl + 3: 0}
    out, dt = sim(hexfile(f"zexdoc-{g}", com, patch), maxclk)
    a = acc_line(out)
    res = out.split("[acc]")[0].replace("\r", "").replace("\n", " ").strip()
    if a and a[0] and not a[2] and re.search(r"\bOK\b", res):
        r = "OK"
    elif a and a[0] and not a[2] and "ERROR" in res:
        r = "ERROR"
    elif a and a[1]:
        r = "TIMEOUT"
    else:
        r = "STOP"
    return g, name, r, a, dt, res


def zexdoc(log, groups, jobs, maxclk):
    path = fetch("zexdoc")
    com = open(path, "rb").read()
    tbl, ptrs = zex_table(com)
    names = [bytes(com[p - 0x100 + 65:]).split(b"$")[0].decode("ascii").strip() for p in ptrs]
    sel = groups if groups is not None else range(len(ptrs))
    extra = [f"# per-group runs ({len(sel)} of {len(ptrs)} groups in this log; all {len(ptrs)} count, decision 9 (b)). Groups 6, 28-31, 48, 50, 59, 60 execute undocumented forms and need",
             "# U1-U3 (chip-z80 #51 ref, #52 Ada SLL, #53 Zura decode); until those merge they are expected to fail, they are NOT skipped.",
             f"# half-clock limit per group {maxclk}; line: group | name | result | done,timeout,bus_conflict,half-clocks | wall s | program output"]
    os.makedirs(os.path.dirname(log), exist_ok=True)
    f = open(log, "w")
    f.write(header("zexdoc", path, extra))
    f.flush()
    res = {}
    with cf.ThreadPoolExecutor(jobs) as ex:
        for g, name, r, a, dt, out in ex.map(one_group, [(g, names[g], com, tbl, ptrs[g], maxclk) for g in sel]):
            res[g] = r
            tag = " [decision 9]" if g in DECISION9 else ""
            f.write(f"{g:2d} | {name} | {r}{tag} | {','.join(map(str, a)) if a else 'no [acc] line'} | {dt:.0f} | {out}\n")
            f.flush()
    ok = sum(r == "OK" for r in res.values())
    bad = [g for g, r in res.items() if r != "OK"]
    f.write(f"# SUMMARY {ok}/{len(res)} OK; not OK: {bad if bad else 'none'}; of those in decision 9: {[g for g in bad if g in DECISION9]}\n")
    f.close()
    print(open(log).read())
    return 0 if not bad else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["build", "prelim", "zexdoc"])
    ap.add_argument("log", nargs="?")
    ap.add_argument("--groups")
    ap.add_argument("--jobs", type=int, default=os.cpu_count())
    ap.add_argument("--maxclk", type=int, default=400_000_000_000)
    a = ap.parse_args()
    if a.what == "build":
        return build()
    if not os.path.exists(BIN):
        build()
    if a.what == "prelim":
        return prelim(a.log or "logs/acc-rtl/prelim.log")
    return zexdoc(a.log or "logs/acc-rtl/zexdoc.log", [int(x) for x in a.groups.split(",")] if a.groups else None, a.jobs, a.maxclk)


if __name__ == "__main__":
    sys.exit(main())
