#!/usr/bin/env python3
"""Sharded zexdoc on GitHub Actions (chip-z80 #78). Owner: Tesla.  Used by .github/workflows/zexdoc.yml.

  scripts/zexdoc_shard.py plan [--groups N,N,..]       print the job matrix as JSON ({"include":[{"id":..,"groups":"a,b"}]})
  scripts/zexdoc_shard.py merge DIR OUT [--expect N,N,..] [--run-url URL]
        Merge every per-shard log (DIR/**/*.log, written by `sw/exerciser/run_rtl.py zexdoc`) into one OUT log:
        same header lines as run_rtl.py (rtl commit, Verilator, zexdoc sha256, decision-9 note), one line per
        group in group order, then the # SUMMARY line. --expect defaults to all 67 groups.
        Exit 0 only if every expected group is present AND OK. A group with no line (shard timed out, crashed, or its
        artifact is missing) is written as MISSING and counts as not OK: it is never dropped.
"""
import argparse, glob, json, os, re, sys

N_GROUPS = 67
DECISION9 = {6, 28, 29, 30, 31, 48, 50, 59, 60}   # same set as sw/exerciser/run_rtl.py
# Long groups run alone (instruction counts: logs/acc-ref/zexdoc-mostek-nmos-summary.log; 5 and 6 are lower bounds / unmeasured).
LONG = [0, 1, 2, 3, 4, 5, 6, 7, 9, 12]
# The other 57 groups, batched so each job builds once and stays well under the 6 h cap (est. <= ~1.5 h at 4 cores).
BATCHES = [[10, 11, 56, 57, 61], [8, 13, 14, 16, 17, 19, 20, 24, 25, 27, 49, 58],
           [15, 18, 21, 22, 23, 26] + list(range(32, 48)) + [51, 52, 53, 54, 55, 62, 63, 64, 65, 66], [28, 29, 30, 31, 48, 50, 59, 60]]
GROUP_LINE = re.compile(r"^\s*(\d+) \| ")


def plan(groups):
    if groups:
        sets = [("sel", groups)]
    else:
        sets = [(f"g{g:02d}", [g]) for g in LONG] + [(f"batch{i + 1}", b) for i, b in enumerate(BATCHES)]
        assert sorted(g for _, s in sets for g in s) == list(range(N_GROUPS)), "plan does not cover 0..66 exactly once"
    return {"include": [{"id": i, "groups": ",".join(map(str, s))} for i, s in sets]}


def merge(d, out, expect, url):
    lines, headers = {}, []
    for p in sorted(glob.glob(os.path.join(d, "**", "*.log"), recursive=True)):
        for l in open(p).read().splitlines():
            m = GROUP_LINE.match(l)
            if m:
                lines[int(m.group(1))] = l
            elif l.startswith("# ") and not l.startswith("# SUMMARY"):
                headers.append((p, l))
    pick = lambda pre: sorted({l for _, l in headers if l.startswith(pre)})
    first = next((l for _, l in headers if l.startswith("# zexdoc on the RTL")), "# zexdoc on the RTL")
    commits = sorted({re.search(r"rtl commit (\w+)", l).group(1) for l in pick("# rtl commit")})
    shas = pick("# zexdoc.com sha256")
    out_l = [first,
             f"# rtl commit {','.join(commits) or '?'}" + ("  ** MIXED COMMITS **" if len(commits) > 1 else "") ,
             shas[0] if shas else "# zexdoc.com sha256 ? (no shard log carried one)",
             f"# sharded run: {len(expect)} of {N_GROUPS} groups in this log; all {N_GROUPS} count, decision 9 (b). Groups 6, 28-31, 48, 50, 59, 60 execute undocumented forms and need",
             "# U1-U3 (chip-z80 #51 ref, #52 Ada SLL, #53 Zura decode); until those merge they are expected to fail, they are NOT skipped.",
             "# line: group | name | result | done,timeout,bus_conflict,half-clocks | wall s | program output (a missing group is MISSING = not OK)"]
    if url:
        out_l.insert(2, f"# run {url}")
    res = {}
    for g in expect:
        if g in lines:
            out_l.append(lines[g])
            res[g] = lines[g].split("|")[2].split()[0]
        else:
            out_l.append(f"{g:2d} | (no shard log) | MISSING | no result line from any shard | 0 | shard timed out, crashed or its artifact is missing")
            res[g] = "MISSING"
    bad = [g for g in expect if res[g] != "OK"]
    out_l.append(f"# SUMMARY {len(expect) - len(bad)}/{len(expect)} OK; not OK: {bad if bad else 'none'}; of those in decision 9: {[g for g in bad if g in DECISION9]}")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    open(out, "w").write("\n".join(out_l) + "\n")
    print("\n".join(out_l))
    return 0 if not bad else 1


def groups_arg(s):
    return sorted({int(x) for x in s.split(",")}) if s else None


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan"); p.add_argument("--groups", default="")
    m = sub.add_parser("merge"); m.add_argument("dir"); m.add_argument("out"); m.add_argument("--expect", default=""); m.add_argument("--run-url", default="")
    a = ap.parse_args()
    if a.cmd == "plan":
        print(json.dumps(plan(groups_arg(a.groups)))); return 0
    return merge(a.dir, a.out, groups_arg(a.expect) or list(range(N_GROUPS)), a.run_url)


if __name__ == "__main__":
    sys.exit(main())
