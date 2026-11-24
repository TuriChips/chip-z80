# Leo: copy a liberty file without the cells we do not want ABC to pick (lpflow_*, probe, clock-gate, etc).
# Usage: python3 filter_lib.py in.lib out.lib
import re, sys
src = open(sys.argv[1]).read()
bad = re.compile(r'sky130_fd_sc_hd__(lpflow_|probe_|bushold|dlygate|dlymetal|clkdlybuf|einv|ebuf|macro|conb)')
out, i, n = [], 0, 0
for m in re.finditer(r'^\s*cell\s*\(\s*"?([^")]+)"?\s*\)\s*\{', src, re.M):
    if m.start() < i:
        continue
    if not bad.search(m.group(1)):
        continue
    out.append(src[i:m.start()])
    depth, j = 0, m.end() - 1
    while True:
        c = src[j]
        depth += (c == '{') - (c == '}')
        j += 1
        if depth == 0:
            break
    i = j
    n += 1
out.append(src[i:])
open(sys.argv[2], 'w').write(''.join(out))
print(f"filter_lib: removed {n} cells")
