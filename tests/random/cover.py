#!/usr/bin/env python3
"""C8 coverage report (Beru, chip-z80#8): per-form execution counts and stimulus kinds over all seeds.

  python3 tests/random/cover.py build/c8/*.cov.json [--min-hits N]
Prints a PASS/FAIL line. Forms are the 698 of spec §6.0 (ref/refz80.census); the EXCLUDED set of gen.py is listed
with its reason and not counted as missing. FAIL if an allowed form was never executed or a stimulus kind never hit.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen  # noqa: E402

KINDS = ["wait_states", "int_asserted", "int_taken_mode0", "int_taken_mode1", "int_taken_mode2", "int_while_halted",
         "int_seen_masked", "int_seen_not_taken_ei_delay", "nmi_asserted", "nmi_taken", "nmi_while_halted",
         "bus_grants", "halt_executed", "halted_m1"]


def key(f):
    return "/".join(str(x) if not isinstance(x, int) else "%02X" % x for x in f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--min-hits", type=int, default=1)
    a = ap.parse_args()
    forms, stim, instr, halves, stops, profiles = {}, {}, 0, 0, {}, {}
    for p in a.files:
        d = json.load(open(p))
        instr += d["instr"]
        halves += d["halves"]
        stops[d["stop"].split(":")[0]] = stops.get(d["stop"].split(":")[0], 0) + 1
        profiles[d["profile"]] = profiles.get(d["profile"], 0) + 1
        for k, v in d["forms"].items():
            forms[k] = forms.get(k, 0) + v
        for k, v in d["stim"].items():
            stim[k] = stim.get(k, 0) + v
    print("seeds %d, instructions %d, half T states %d" % (len(a.files), instr, halves))
    print("profiles:", ", ".join("%s %d" % kv for kv in sorted(profiles.items())))
    print("run ends:", ", ".join("%s %d" % kv for kv in sorted(stops.items())))
    print("\nstimulus kinds hit (total over seeds):")
    miss_k = [k for k in KINDS if stim.get(k, 0) == 0]
    for k in KINDS:
        print("  %-30s %d" % (k, stim.get(k, 0)))
    print("  other:", {k: v for k, v in sorted(stim.items()) if k not in KINDS})
    print("\nexcluded forms (gen.EXCLUDED, never emitted):")
    for f, why in sorted(gen.EXCLUDED.items(), key=lambda kv: str(kv[0])):
        print("  %-12s %s" % (key(f), why))
    allowed = [key(f) for f in gen.FORMS]
    low = [k for k in allowed if forms.get(k, 0) < a.min_hits]
    counts = sorted(forms.get(k, 0) for k in allowed)
    print("\nper-form executed counts, %d allowed forms (%d forms in all, %d excluded):" % (len(allowed), len(gen.ALL_FORMS), len(gen.EXCLUDED)))
    print("  min %d  median %d  max %d  forms below %d hits: %d" % (counts[0], counts[len(counts) // 2], counts[-1], a.min_hits, len(low)))
    groups = {}
    for k in allowed:
        g = k.split("/")[0] if k.split("/")[0] != "main" else "main"
        if len(k.split("/")) == 3: g += " CB"
        groups.setdefault(g, [0, 0, 0])
        groups[g][0] += 1
        groups[g][1] += forms.get(k, 0) > 0
        groups[g][2] += forms.get(k, 0)
    for g, (n, hit, tot) in sorted(groups.items()):
        print("  %-8s %3d forms, %3d hit, %6d executions" % (g, n, hit, tot))
    print("\nform  count   (all allowed forms)")
    for k in allowed:
        print("%-12s %d" % (k, forms.get(k, 0)))
    if low:
        print("\nFAIL: %d form(s) below %d hits: %s" % (len(low), a.min_hits, " ".join(low)))
    if miss_k:
        print("FAIL: stimulus kinds never hit: %s" % " ".join(miss_k))
    bad = [k for k in stops if k.startswith("model-raised")]
    if bad:
        print("FAIL: %d run(s) ended with the model raising Undocumented/Unspecified: a generator bug, the trial run should have rejected it" % stops[bad[0]])
    if low or miss_k or bad:
        return 1
    print("\nPASS coverage: every allowed form executed >= %d times, every stimulus kind hit" % a.min_hits)
    return 0


if __name__ == "__main__":
    sys.exit(main())
