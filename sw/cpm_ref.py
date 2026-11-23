#!/usr/bin/env python3
"""Minimal CP/M stub around ref/refz80.py: runs a .COM acceptance program on the reference model.

Memory map: .COM loaded at 0100H; 0000H = JP 0 (warm boot, stops the run); 0005H = JP BDOS;
BDOS entry at FE00H, so 0006H/0007H = FE00H = the true top of the TPA (the 8080 lesson, spec §9:
zexdoc does LD SP,(0006H), so a wrong top of memory puts its stack on top of the BDOS).
BDOS calls handled: C=2 (console out, E), C=9 (print string at DE, '$' terminated). Anything else stops the run.

Usage: sw/cpm_ref.py PROG.COM [--x6 raise|taint|mostek] [--daa raise|taint|nmos] [--limit SECONDS]
                              [--lenient-push] [--groups [N,N,..]]   (zexdoc only: run each test group on its own)
Exit: 0 = ran to JP 0000H, 1 = Unspecified raise, 2 = time limit, 3 = bad BDOS call / HALT.
"""
import argparse, os, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ref"))
from refz80 import Z80, Policy, Unspecified, Undocumented  # noqa: E402

BDOS = 0xFE00


class Fast(Z80):
    """step() without the `last` trace. ref's step() builds `last` with range((pc - start) & 0xFFFF), which
    after every taken jump/call is thousands of bytes: ~800 instr/s, 100x too slow for zexdoc (finding for
    Beru). This stub never raises INT/NMI, so skipping that branch of step() changes nothing else."""

    def step(self):
        if self.halted or self.nmi_pending or self.int_line:
            return super().step()
        self.ei_delay = False
        return self.execute()


class LenientPush(Fast):
    """Run mode --lenient-push: PUSH AF no longer raises on an X flag (the flag is then treated as defined).
    Only for zexdoc, whose own housekeeping PUSHes AF after ADD HL,DE (H = X, spec §6.2) and whose test
    masks hide X flags anyway. Without it zexdoc cannot start at all (finding, chip-z80 issue). The strict
    model is untouched: this subclass lives here, ref/ is Beru's."""

    def need(self, mask, what):
        if what != "PUSH AF":
            super().need(mask, what)


class Stop(Exception):
    def __init__(self, why, code):
        self.why, self.code = why, code


def make(com, policy, lenient=False):
    cpu = (LenientPush if lenient else Fast)(policy)
    m = cpu.mem
    m[0:3] = bytes([0xC3, 0x00, 0x00])
    m[5:8] = bytes([0xC3, BDOS & 255, BDOS >> 8])     # 0006/0007 = BDOS address = top of memory
    m[BDOS] = 0xC9
    m[0x100:0x100 + len(com)] = com
    cpu.pc, cpu.sp = 0x100, BDOS - 2                  # CCP-ish stack: return address 0000H
    m[cpu.sp:cpu.sp + 2] = bytes([0, 0])
    return cpu


def run(cpu, out, limit, deadline=None):
    """Runs until JP 0. Returns instruction count. Raises Stop."""
    n = 0
    t0 = time.time()
    while True:
        if cpu.pc == BDOS:
            c = cpu.reg[1]
            if c == 2:
                out(chr(cpu.reg[3] & 127))
            elif c == 9:
                a = cpu.reg[2] << 8 | cpu.reg[3]
                while cpu.mem[a] != 0x24:
                    out(chr(cpu.mem[a] & 127))
                    a = (a + 1) & 0xFFFF
            else:
                raise Stop(f"unhandled BDOS function C={c:02X}", 3)
        elif cpu.pc == 0 and n:
            return n
        if cpu.halted:
            raise Stop(f"HALT at {cpu.pc - 1:04X}", 3)
        cpu.step()
        n += 1
        if not n & 0x3FFF and time.time() - t0 > limit:
            raise Stop(f"time limit {limit}s after {n} instructions", 2)


def find_table(com):
    """zexdoc: start does `ld hl,tests` then `ld a,(hl); inc hl; or (hl); jp z,...` (21 lo hi 7E 23 B6 CA)."""
    i = bytes(com).find(bytes([0x7E, 0x23, 0xB6, 0xCA]))
    assert i >= 3 and com[i - 3] == 0x21, "not a zexdoc .com (test table not found)"
    return (com[i - 2] | com[i - 1] << 8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("com")
    ap.add_argument("--x6", default="raise")
    ap.add_argument("--daa", default="raise")
    ap.add_argument("--limit", type=float, default=600, help="seconds (per group with --groups)")
    ap.add_argument("--lenient-push", action="store_true", help="PUSH AF of an X flag does not raise (zexdoc only)")
    ap.add_argument("--groups", nargs="?", const="all")
    a = ap.parse_args()
    com = open(a.com, "rb").read()
    pol = lambda: Policy(x6=a.x6, daa=a.daa)
    print(f"# cpm_ref: {os.path.basename(a.com)} {len(com)} bytes, policy x6={a.x6} daa={a.daa}{' lenient-push' if a.lenient_push else ''}, limit {a.limit}s", flush=True)

    def out(ch):
        sys.stdout.write(ch.replace("\r", ""))
        sys.stdout.flush()

    if a.groups is None:
        cpu = make(com, pol(), a.lenient_push)
        t0 = time.time()
        try:
            n = run(cpu, out, a.limit)
            print(f"\n# JP 0000H after {n} instructions, {time.time() - t0:.1f}s")
            return 0
        except Undocumented as e:
            print(f"\n# UNDOCUMENTED opcode {e} at PC={cpu.pc:04X}")
            return 1
        except Unspecified as e:
            print(f"\n# UNSPECIFIED at PC={cpu.pc:04X} [{cpu.last[:23]}]: {e}")
            return 1
        except Stop as e:
            print(f"\n# STOP: {e.why} (PC={cpu.pc:04X})")
            return e.code
    tbl = find_table(com)
    ptrs = []
    while com[tbl - 0x100 + 2 * len(ptrs)] | com[tbl - 0x100 + 2 * len(ptrs) + 1] << 8:
        k = tbl - 0x100 + 2 * len(ptrs)
        ptrs.append(com[k] | com[k + 1] << 8)
    sel = range(len(ptrs)) if a.groups == "all" else [int(x) for x in a.groups.split(",")]
    worst = 0
    print("# group | result | instructions | seconds | detail")
    for g in sel:
        cpu = make(com, pol(), a.lenient_push)
        cpu.mem[tbl:tbl + 4] = bytes([ptrs[g] & 255, ptrs[g] >> 8, 0, 0])
        name = bytes(com[ptrs[g] - 0x100 + 65:]).split(b"$")[0].decode("ascii")
        buf = []
        t0 = time.time()
        try:
            n = run(cpu, buf.append, a.limit)
            res = "".join(buf).replace("\n", " ").strip()
            res = res[res.find(name):] if name in res else res
            r = "OK" if " OK" in res else "ERROR"
            detail = res
        except Unspecified as e:
            n, r, detail = 0, "UNSPECIFIED", f"PC={cpu.pc:04X} [{cpu.last[:23]}]: {e}"
        except Undocumented as e:
            n, r, detail = 0, "UNDOCUMENTED", f"opcode {e} is outside the 1977 manuals (spec §6.0)"
        except Stop as e:
            n, r, detail = 0, "TIMEOUT" if e.code == 2 else "STOP", e.why
        print(f"{g:2d} {name.strip()} | {r} | {n} | {time.time() - t0:.0f} | {detail}", flush=True)
        worst = max(worst, 0 if r == "OK" else 1)
    return worst


if __name__ == "__main__":
    sys.exit(main())
