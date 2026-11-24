#!/usr/bin/env python3
"""Generates rtl/control/z80_decode.v and rtl/control/z80_decode_kinds.vh (docs/blocks.md section 3, z80_decode).

Usage:
  python3 rtl/control/gen_decode.py [--spec docs/spec.md] [--check]
    (no flag)  build the table, run the checks, write the two files
    --check    build the table, run the checks, and verify the committed files equal the regenerated text

The table below is the encoding, written from the instruction set (spec 6.0/6.1), never from the ref model. The checks:
  1. the 698 documented forms == ref/refz80.py census() (per group main 252, CB 248, DD 70, ED 58, FD 70); the 152 forms
     of decision 9 (spec 6.0a: U1 92, U2 50, U3 10) are enumerated here from the spec's rules, and once the ref model
     has them too (census() = 850) the whole table must equal census() exactly;
  2. every form's M-cycle types and lengths equal the spec 6.1 table row it names (parsed from the spec text);
  3. every form's T states, for each outcome (condition met / not met, repeating / not), equal what ref/refz80.py's
     step() returns for that form.
Encodings outside the 850 decode as specified = 0 with the NOP plan (control treats them as NOP and tests never run them).

Decision 9 (b), spec 6.0a: the 152 extra forms are table rows like any other (specified = 1):
  U1  DD/FD + 92 opcodes naming H/L as an 8-bit register: the unprefixed kind (LD_R_R, LD_R_N, INC_R, DEC_R, ALU_R) with
      one extra OCF(4) first; z80_control substitutes IXH/IXL/IYH/IYL (r8 8-11) for r = 4, 5 in those kinds under DD/FD;
  U2  DD/FD + LD r,r' on B,C,D,E,A: LD_R_R with the extra OCF(4), no substitution;
  U3  SLL: CB 30-37 and DD/FD CB d 36 are ROT_R / ROT_HL / ROT_IXD with ir[5:3] = 6, so alu_op 11 + 6 = 17.

Decode output (all combinational from {prefix, ir}); a "plan" always covers the WHOLE instruction, from the first
fetch (prefix fetches and the d / op bytes of DD CB d op included):
  specified   1   the form is one of the 850 (698 documented + decision 9's 152)
  is_prefix   1   this byte only selects a prefix: prefix 0 and ir in CB DD ED FD, or prefix 2/4 and ir = CB.
                  The plan is then OCF(4) and control fetches on (specified = 0 for it)
  ins         7   instruction kind, z80_decode_kinds.vh (`Z80K_*); one per semantic, see the table below
  pn          3   M cycles when the instruction runs its full plan (condition met / repeating)
  pn_s        3   M cycles when the condition is not met / the block instruction ends (= pn when no condition)
  s3          1   CALL cc not met: M3 is 3 T (the full plan has ODH(4)); the other short plans are prefixes of the full one
  plan_type  18   6 x 3 bits, M cycle k at [3k+:3]: mc_type of blocks.md 2.1 (OCF 0, MRD 1, MWR 2, PRD 3, PWR 4, IO 5)
  plan_len   18   6 x 3 bits, M cycle k at [3k+:3]: mc_len, as spec 6.1 writes it
The condition itself (cc from ir, BC != 0, B != 0, A = (HL)) is read in z80_control from `ir` and the flags.
"""
import re, sys, os, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(HERE + "/../..")
args = sys.argv[1:]
CHECK_ONLY = "--check" in args
specf = ROOT + "/docs/spec.md"
if "--spec" in args:
    specf = args[args.index("--spec") + 1]

TYPES = {"OCF": 0, "MR": 1, "MW": 2, "PR": 3, "PW": 4, "IO": 5}
PREFIX = {"": 0, "CB": 1, "DD": 2, "ED": 3, "FD": 4, "DDCB": 5, "FDCB": 6}

kinds = []              # kind names in order; code = index
forms = {}              # (prefix_code, op) -> dict

def P(s):
    return [(m.group(1), int(m.group(2))) for m in re.finditer(r"([A-Z]+)(\d)", s)]

def kind(name):
    if name not in kinds:
        kinds.append(name)
    return kinds.index(name)

def put(pre, op, name, plan, row, short=None, srow=None, mnem="", extra=False, lead=0):
    """pre in '', CB, DD, ED, FD, DDCB, FDCB. plan: 'OCF4 OD3' style (OD, MR, SRL... all spelled MR/MW here).
    row: label of the spec 6.1 table row for the full plan; short/srow: the same for the not-met / ends outcome.
    extra: a decision 9 form (not one of the 698). lead: leading cycles of the plan that are not in the row (U1/U2 prefix OCF)."""
    key = (PREFIX[pre], op)
    assert key not in forms, (pre, hex(op))
    forms[key] = dict(kind=kind(name), plan=P(plan), row=row, short=P(short) if short else None, srow=srow, mnem=mnem or name, extra=extra, lead=lead)

R8 = ["B", "C", "D", "E", "H", "L", "(HL)", "A"]

# ------------------------------------------------------------------ unprefixed
for op in range(256):
    if op in (0xCB, 0xDD, 0xED, 0xFD):
        continue
    x, y, z, p, q = op >> 6, (op >> 3) & 7, op & 7, (op >> 4) & 3, (op >> 3) & 1
    if x == 0:
        if z == 0:
            if y == 0: put("", op, "NOP", "OCF4", "DAA; CPL; CCF; SCF; NOP; HALT; DI; EI")
            elif y == 1: put("", op, "EX_AF", "OCF4", "EX DE,HL; EX AF,AF'; EXX")
            elif y == 2: put("", op, "DJNZ", "OCF5 MR3 IO5", "DJNZ e: B ≠ 0 after the decrement", "OCF5 MR3", "DJNZ e: B = 0")
            elif y == 3: put("", op, "JR", "OCF4 MR3 IO5", "JR e")
            else: put("", op, "JR_CC", "OCF4 MR3 IO5", "JR C/NC/Z/NZ,e: condition met", "OCF4 MR3", "JR C/NC/Z/NZ,e: not met")
        elif z == 1:
            if q == 0: put("", op, "LD_DD_NN", "OCF4 MR3 MR3", "LD dd,nn")
            else: put("", op, "ADD_HL_SS", "OCF4 IO4 IO3", "ADD HL,ss")
        elif z == 2:
            if y in (0, 2): put("", op, "LD_RP_A", "OCF4 MW3", "LD (BC),A; LD (DE),A")
            elif y in (1, 3): put("", op, "LD_A_RP", "OCF4 MR3", "LD A,(BC); LD A,(DE)")
            elif y == 4: put("", op, "LD_NN_HL", "OCF4 MR3 MR3 MW3 MW3", "LD (nn),HL")
            elif y == 5: put("", op, "LD_HL_NN", "OCF4 MR3 MR3 MR3 MR3", "LD HL,(nn)")
            elif y == 6: put("", op, "LD_NN_A", "OCF4 MR3 MR3 MW3", "LD (nn),A")
            else: put("", op, "LD_A_NN", "OCF4 MR3 MR3 MR3", "LD A,(nn)")
        elif z == 3: put("", op, "DEC_SS" if q else "INC_SS", "OCF6", "INC ss; DEC ss")
        elif z in (4, 5):
            n = "INC" if z == 4 else "DEC"
            if y == 6: put("", op, n + "_HL", "OCF4 MR4 MW3", "INC (HL); DEC (HL)")
            else: put("", op, n + "_R", "OCF4", "INC r; DEC r")
        elif z == 6:
            if y == 6: put("", op, "LD_HL_N", "OCF4 MR3 MW3", "LD (HL),n")
            else: put("", op, "LD_R_N", "OCF4 MR3", "LD r,n")
        else:
            if y < 4: put("", op, "ROT_A", "OCF4", "RLCA; RLA; RRCA; RRA")
            else: put("", op, ["DAA", "CPL", "SCF", "CCF"][y - 4], "OCF4", "DAA; CPL; CCF; SCF; NOP; HALT; DI; EI")
    elif x == 1:
        if op == 0x76: put("", op, "HALT", "OCF4", "DAA; CPL; CCF; SCF; NOP; HALT; DI; EI")
        elif y == 6: put("", op, "LD_HL_R", "OCF4 MW3", "LD (HL),r")
        elif z == 6: put("", op, "LD_R_HL", "OCF4 MR3", "LD r,(HL)")
        else: put("", op, "LD_R_R", "OCF4", "LD r,r'")
    elif x == 2:
        if z == 6: put("", op, "ALU_HL", "OCF4 MR3", "alu (HL)")
        else: put("", op, "ALU_R", "OCF4", "alu r")
    else:
        if z == 0: put("", op, "RET_CC", "OCF5 MR3 MR3", "RET cc, cc true", "OCF5", "RET cc, cc false")
        elif z == 1:
            if q == 0: put("", op, "POP", "OCF4 MR3 MR3", "POP qq")
            else:
                nm = {0: "RET", 2: "EXX", 4: "JP_HL", 6: "LD_SP_HL"}[p * 2]
                if nm == "RET": put("", op, nm, "OCF4 MR3 MR3", "RET")
                elif nm == "EXX": put("", op, nm, "OCF4", "EX DE,HL; EX AF,AF'; EXX")
                elif nm == "JP_HL": put("", op, nm, "OCF4", "JP (HL)")
                else: put("", op, nm, "OCF6", "LD SP,HL")
        elif z == 2: put("", op, "JP_CC", "OCF4 MR3 MR3", "JP nn; JP cc,nn (either outcome)")
        elif z == 3:
            if y == 0: put("", op, "JP", "OCF4 MR3 MR3", "JP nn; JP cc,nn (either outcome)")
            elif y == 2: put("", op, "OUT_N_A", "OCF4 MR3 PW4", "OUT (n),A")
            elif y == 3: put("", op, "IN_A_N", "OCF4 MR3 PR4", "IN A,(n)")
            elif y == 4: put("", op, "EX_SP_HL", "OCF4 MR3 MR4 MW3 MW5", "EX (SP),HL")
            elif y == 5: put("", op, "EX_DE_HL", "OCF4", "EX DE,HL; EX AF,AF'; EXX")
            elif y == 6: put("", op, "DI", "OCF4", "DAA; CPL; CCF; SCF; NOP; HALT; DI; EI")
            else: put("", op, "EI", "OCF4", "DAA; CPL; CCF; SCF; NOP; HALT; DI; EI")
        elif z == 4: put("", op, "CALL_CC", "OCF4 MR3 MR4 MW3 MW3", "CALL nn; CALL cc,nn with cc true",
                         "OCF4 MR3 MR3", "CALL cc,nn with cc false")
        elif z == 5:
            if q == 0: put("", op, "PUSH", "OCF5 MW3 MW3", "PUSH qq")
            else: put("", op, "CALL", "OCF4 MR3 MR4 MW3 MW3", "CALL nn; CALL cc,nn with cc true")
        elif z == 6: put("", op, "ALU_N", "OCF4 MR3", "alu n")
        else: put("", op, "RST", "OCF5 MW3 MW3", "RST p")
# ------------------------------------------------------------------ CB
for op in range(256):
    x, y, z = op >> 6, (op >> 3) & 7, op & 7
    sll = (x == 0 and y == 6)                        # U3: SLL, decision 9
    if x == 0:
        if z == 6: put("CB", op, "ROT_HL", "OCF4 OCF4 MR4 MW3", "rot (HL)", extra=sll)
        else: put("CB", op, "ROT_R", "OCF4 OCF4", "rot r", extra=sll)
    elif x == 1:
        if z == 6: put("CB", op, "BIT_HL", "OCF4 OCF4 MR4", "BIT b,(HL)")
        else: put("CB", op, "BIT_R", "OCF4 OCF4", "BIT b,r; SET b,r; RES b,r")
    else:
        nm = "RES" if x == 2 else "SET"
        if z == 6: put("CB", op, nm + "_HL", "OCF4 OCF4 MR4 MW3", "SET b,(HL); RES b,(HL)")
        else: put("CB", op, nm + "_R", "OCF4 OCF4", "BIT b,r; SET b,r; RES b,r")
# ------------------------------------------------------------------ ED
for op in range(0x40, 0x80):
    x, y, z, p, q = 1, (op >> 3) & 7, op & 7, (op >> 4) & 3, (op >> 3) & 1
    if z == 0 and y != 6: put("ED", op, "IN_R_C", "OCF4 OCF4 PR4", "IN r,(C)")
    elif z == 1 and y != 6: put("ED", op, "OUT_C_R", "OCF4 OCF4 PW4", "OUT (C),r")
    elif z == 2: put("ED", op, "ADC_HL" if q else "SBC_HL", "OCF4 OCF4 IO4 IO3", "ADC HL,ss; SBC HL,ss")
    elif z == 3: put("ED", op, "LD_DD_NN_IND" if q else "LD_NN_DD", "OCF4 OCF4 MR3 MR3 " + ("MR3 MR3" if q else "MW3 MW3"),
                     "LD dd,(nn) (ED 4B/5B/6B/7B)" if q else "LD (nn),dd (ED 43/53/63/73)")
    elif z == 4 and y == 0: put("ED", op, "NEG", "OCF4 OCF4", "NEG; IM 0; IM 1; IM 2")
    elif z == 5 and y == 0: put("ED", op, "RETN", "OCF4 OCF4 MR3 MR3", "RETI; RETN")
    elif z == 5 and y == 1: put("ED", op, "RETI", "OCF4 OCF4 MR3 MR3", "RETI; RETN")
    elif z == 6 and y in (0, 2, 3): put("ED", op, "IM", "OCF4 OCF4", "NEG; IM 0; IM 1; IM 2")
    elif z == 7 and y < 4: put("ED", op, ["LD_I_A", "LD_R_A", "LD_A_I", "LD_A_R"][y], "OCF4 OCF5", "LD A,I; LD A,R; LD I,A; LD R,A")
    elif z == 7 and y in (4, 5): put("ED", op, "RRD" if y == 4 else "RLD", "OCF4 OCF4 MR3 IO4 MW3", "RLD; RRD")
for op in range(0xA0, 0xC0):
    y, z = (op >> 3) & 7, op & 7
    if z > 3 or y < 4:
        continue
    kd = ("LD", "CP", "IN", "OUT")[z]
    nm = kd + ("I" if y & 1 == 0 else "D") + ("R" if y >= 6 else "")
    pair = {"LD": "LDI; LDD", "CP": "CPI; CPD", "IN": "INI; IND", "OUT": "OUTI; OUTD"}[kd]
    base = {"LD": "OCF4 OCF4 MR3 MW5", "CP": "OCF4 OCF4 MR3 IO5", "IN": "OCF4 OCF5 PR4 MW3", "OUT": "OCF4 OCF5 MR3 PW4"}[kd]
    if y < 6:
        put("ED", op, nm, base, pair)
    else:
        rep = {"LD": "LDIR; LDDR", "CP": "CPIR; CPDR", "IN": "INIR; INDR", "OUT": "OTIR; OTDR"}[kd]
        put("ED", op, nm, base + " IO5", rep, base, pair)
# ------------------------------------------------------------------ DD / FD
for pre in ("DD", "FD"):
    for op in range(256):
        if op in (0x09, 0x19, 0x29, 0x39): put(pre, op, "ADD_IX", "OCF4 OCF4 IO4 IO3", "ADD IX,pp; ADD IY,rr")
        elif op == 0x21: put(pre, op, "LD_IX_NN", "OCF4 OCF4 MR3 MR3", "LD IX,nn; LD IY,nn")
        elif op == 0x22: put(pre, op, "LD_NN_IX", "OCF4 OCF4 MR3 MR3 MW3 MW3", "LD (nn),IX; LD (nn),IY")
        elif op == 0x2A: put(pre, op, "LD_IX_NNI", "OCF4 OCF4 MR3 MR3 MR3 MR3", "LD IX,(nn); LD IY,(nn)")
        elif op in (0x23, 0x2B): put(pre, op, "DEC_IX" if op == 0x2B else "INC_IX", "OCF4 OCF6", "INC IX; DEC IX; INC IY; DEC IY")
        elif op in (0x34, 0x35): put(pre, op, "DEC_IXD" if op == 0x35 else "INC_IXD", "OCF4 OCF4 MR3 IO5 MR4 MW3", "INC (IX+d); DEC (IX+d); same for IY")
        elif op == 0x36: put(pre, op, "LD_IXD_N", "OCF4 OCF4 MR3 MR5 MW3", "LD (IX+d),n; LD (IY+d),n")
        elif op in (0x46, 0x4E, 0x56, 0x5E, 0x66, 0x6E, 0x7E): put(pre, op, "LD_R_IXD", "OCF4 OCF4 MR3 IO5 MR3", "LD r,(IX+d); LD r,(IY+d)")
        elif op in (0x70, 0x71, 0x72, 0x73, 0x74, 0x75, 0x77): put(pre, op, "LD_IXD_R", "OCF4 OCF4 MR3 IO5 MW3", "LD (IX+d),r; LD (IY+d),r")
        elif op in (0x86, 0x8E, 0x96, 0x9E, 0xA6, 0xAE, 0xB6, 0xBE): put(pre, op, "ALU_IXD", "OCF4 OCF4 MR3 IO5 MR3", "alu (IX+d); alu (IY+d)")
        elif op == 0xE1: put(pre, op, "POP_IX", "OCF4 OCF4 MR3 MR3", "POP IX; POP IY")
        elif op == 0xE3: put(pre, op, "EX_SP_IX", "OCF4 OCF4 MR3 MR4 MW3 MW5", "EX (SP),IX; EX (SP),IY")
        elif op == 0xE5: put(pre, op, "PUSH_IX", "OCF4 OCF5 MW3 MW3", "PUSH IX; PUSH IY")
        elif op == 0xE9: put(pre, op, "JP_IX", "OCF4 OCF4", "JP (IX); JP (IY)")
        elif op == 0xF9: put(pre, op, "LD_SP_IX", "OCF4 OCF6", "LD SP,IX; LD SP,IY")
    # U1 (halves) and U2 (no-effect prefix), spec 6.0a: the unprefixed form with one more OCF(4) in front
    for op in range(256):
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        if x == 1 and y != 6 and z != 6:
            put(pre, op, "LD_R_R", "OCF4 OCF4", "LD r,r'", extra=True, lead=1)      # U1 if hl else U2
        elif x == 0 and z == 6 and y in (4, 5): put(pre, op, "LD_R_N", "OCF4 OCF4 MR3", "LD r,n", extra=True, lead=1)
        elif x == 0 and z in (4, 5) and y in (4, 5): put(pre, op, "INC_R" if z == 4 else "DEC_R", "OCF4 OCF4", "INC r; DEC r", extra=True, lead=1)
        elif x == 2 and z in (4, 5): put(pre, op, "ALU_R", "OCF4 OCF4", "alu r", extra=True, lead=1)
    for op in range(256):
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        if z != 6:
            continue
        if x == 0: put(pre + "CB", op, "ROT_IXD", "OCF4 OCF4 MR3 MR5 MR4 MW3", "rot (IX+d); rot (IY+d)", extra=(y == 6))
        elif x == 1: put(pre + "CB", op, "BIT_IXD", "OCF4 OCF4 MR3 MR5 MR4", "BIT b,(IX+d); BIT b,(IY+d)")
        else: put(pre + "CB", op, "RES_IXD" if x == 2 else "SET_IXD", "OCF4 OCF4 MR3 MR5 MR4 MW3", "SET/RES b,(IX+d); same for IY")
# ------------------------------------------------------------------ prefix bytes (not forms)
PREFIX_ONLY = {(0, 0xCB), (0, 0xDD), (0, 0xED), (0, 0xFD), (2, 0xCB), (4, 0xCB)}
kind("PREFIX")

# ------------------------------------------------------------------ checks
def census_set():
    sys.path.insert(0, ROOT + "/ref")
    import refz80
    fs, groups = refz80.census()
    out = set()
    for f in fs:
        if f[0] == "main": out.add((0, f[1]))
        elif len(f) == 3: out.add((PREFIX[f[0] + "CB"], f[2]))
        else: out.add((PREFIX[f[0]], f[1]))
    return out, groups

def norm_label(s):
    return re.sub(r"\s+", " ", s.replace("*", "")).strip()

def spec_rows(text):
    """label -> list of (type, len) from the 6.1 tables. Spec type names are folded into our 6 types."""
    s = text[text.index("### 6.1 "):]
    s = s[:s.index("### 6.1a")]
    rows = {}
    def fold(t):
        if t in ("OCF", "IO", "PR", "PW"): return t
        if t in ("OD", "ODL", "ODH", "MR", "MRL", "MRH", "SRL", "SRH"): return "MR"
        if t in ("MW", "MWL", "MWH", "SWL", "SWH"): return "MW"
        raise ValueError(t)
    for line in s.splitlines():
        if not line.startswith("|"): continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5 or cells[0] in ("Instruction", "---") or set(cells[0]) <= set("-"): continue
        lab, cyc = norm_label(cells[0]), cells[4]
        m = re.match(r"as ([A-Z/]+), plus IO\(5\)", cyc)
        if m:
            rows[lab] = ("as", m.group(1), [("IO", 5)])
            continue
        cyc = cyc.replace("*", "")
        if "Derived" in cyc: cyc = cyc[cyc.index("Derived"):]
        toks = [(fold(a), int(b)) for a, b in re.findall(r"\b([A-Z]{2,3})\((\d)\)", cyc)]
        rows[lab] = ("seq", toks)
    return rows

BASE = {"LDI/LDD": "LDI; LDD", "CPI/CPD": "CPI; CPD", "INI/IND": "INI; IND", "OUTI/OUTD": "OUTI; OUTD"}
def row_plan(rows, lab):
    r = rows[norm_label(lab)]
    if r[0] == "seq": return r[1]
    return row_plan(rows, BASE[r[1]]) + r[2]

def sum_t(plan): return sum(l for _, l in plan)

def run_checks():
    log = []
    ok = True
    def say(s): log.append(s)
    # 1. census. The 698 documented forms must equal the ref model's; the 152 of decision 9 are checked against it
    #    only once the ref model has them (census() = 850), and always against the spec's counts (92 + 50 + 10).
    cs, groups = census_set()
    mine = {k for k in forms}
    doc = {k for k, f in forms.items() if not f["extra"]}
    ext = mine - doc
    say(f"forms in the table: {len(mine)} = {len(doc)} documented + {len(ext)} decision 9; ref census: {len(cs)} {groups}")
    ref_has_ext = len(cs) > 698
    cmp_set = mine if ref_has_ext else doc
    only_t, only_r = sorted(cmp_set - cs), sorted(cs - cmp_set)
    say(f"in table, not in census: {len(only_t)} {only_t[:8]}; in census, not in table: {len(only_r)} {only_r[:8]}"
        + ("" if ref_has_ext else "  (the ref model does not have the 152 yet: compared on the 698 only)"))
    ok &= not only_t and not only_r and len(doc) == 698 and len(mine) == 850
    pre_names = ["main", "CB", "DD", "ED", "FD", "DDCB", "FDCB"]
    cnt = {n: sum(1 for k in doc if k[0] == i) for i, n in enumerate(pre_names)}
    say(f"documented per prefix: {cnt}; spec 6.0: main 252, CB 248, DD 70 (39 + 31 DDCB), ED 58, FD 70")
    ok &= (cnt["main"], cnt["CB"], cnt["DD"] + cnt["DDCB"], cnt["ED"], cnt["FD"] + cnt["FDCB"]) == (252, 248, 70, 58, 70)
    sll = {k for k in ext if k[0] in (1, 5, 6)}
    u12 = {k for k in ext if k[0] in (2, 4)}
    u1 = {k for k in u12 if forms[k]["kind"] != kinds.index("LD_R_R") or (k[1] >> 3 & 7 in (4, 5)) or (k[1] & 7 in (4, 5))}
    say(f"decision 9: U1 {len(u1)} (spec 92), U2 {len(u12) - len(u1)} (spec 50), U3 SLL {len(sll)} (spec 10)")
    ok &= (len(u1), len(u12) - len(u1), len(sll)) == (92, 50, 10)
    # 2. plan vs spec text
    text = open(specf, encoding="utf-8").read()
    rows = spec_rows(text)
    say(f"spec 6.1 rows parsed from {os.path.relpath(specf, ROOT) if specf.startswith(ROOT) else specf}: {len(rows)}")
    bad = 0
    for k, f in sorted(forms.items()):
        for plan, lab, what in ((f["plan"], f["row"], "full"), (f["short"], f["srow"], "short")):
            if plan is None: continue
            try:
                want = [("OCF", 4)] * f["lead"] + row_plan(rows, lab)
            except KeyError:
                say(f"  NO SPEC ROW {lab!r} for {pre_names[k[0]]} {k[1]:02X}"); bad += 1; continue
            if plan != want:
                say(f"  PLAN MISMATCH {pre_names[k[0]]} {k[1]:02X} {what} {lab!r}: table {plan} spec {want}"); bad += 1
    say(f"plan vs spec 6.1: {len(forms)} forms, {bad} mismatches")
    ok &= bad == 0
    # 3. T states vs the ref model
    sys.path.insert(0, ROOT + "/ref")
    import refz80
    bad = 0
    for k, f in sorted(forms.items()):
        want = {sum_t(f["plan"])} | ({sum_t(f["short"])} if f["short"] else set())
        if f["extra"] and not ref_has_ext:
            continue                                 # no ref-model step() for these yet; plan vs spec rows above covers them
        got = set()
        seqs = {0: lambda o: [o], 1: lambda o: [0xCB, o], 2: lambda o: [0xDD, o, 5], 3: lambda o: [0xED, o],
                4: lambda o: [0xFD, o, 5], 5: lambda o: [0xDD, 0xCB, 5, o], 6: lambda o: [0xFD, 0xCB, 5, o]}
        for F in (0x00, 0xFF):
            for A in (0, 1):
                for BC in (0x0000, 0x0001, 0x0102, 0x0201):
                    c = refz80.Z80(refz80.Policy("taint", "taint"))
                    c.pc, c.sp = 0x100, 0x8000
                    seq = seqs[k[0]](k[1])
                    c.mem[0x100:0x100 + len(seq)] = bytes(seq + [0, 0, 0])
                    c.f, c.a = F, A
                    c.reg[0], c.reg[1] = BC >> 8, BC & 255
                    c.set_rp(2, 0x200)
                    c.ix = c.iy = 0x200
                    try:
                        got.add(c.step())
                    except (refz80.Undocumented, refz80.Unspecified) as e:
                        if isinstance(e, refz80.Undocumented):
                            got.add(("UNDOC",))
        if got != want:
            say(f"  T MISMATCH {pre_names[k[0]]} {k[1]:02X} {f['mnem']}: table {sorted(want)} ref {sorted(got, key=str)}"); bad += 1
    say(f"T states vs ref step(): {len(doc) if not ref_has_ext else len(forms)} forms, {bad} mismatches")
    ok &= bad == 0
    return ok, log

# ------------------------------------------------------------------ emit
def emit():
    names = kinds
    assert len(names) <= 128
    vh = ["// Generated by rtl/control/gen_decode.py: do not edit. z80_decode `ins` kind codes.",
          "// One kind per instruction semantic; the condition and register fields are read from `ir` in z80_control."]
    for i, n in enumerate(names):
        vh.append(f"`define Z80K_{n} 7'd{i}")
    vh.append("")
    L = []
    w = L.append
    w("// Generated by rtl/control/gen_decode.py from its table: do not edit by hand.")
    w("// z80_decode: {prefix, ir} -> specified, is_prefix, instruction kind and the cycle plan.")
    w("// Ports and encoding: docs/blocks.md section 3 (z80_decode), see the header of gen_decode.py for the fields.")
    w("// prefix: 0 none, 1 CB, 2 DD, 3 ED, 4 FD, 5 DD CB, 6 FD CB. Kinds: z80_decode_kinds.vh.")
    w("module z80_decode (")
    w("    input  wire [2:0]  prefix,")
    w("    input  wire [7:0]  ir,")
    w("    output wire        specified,")
    w("    output wire        is_prefix,")
    w("    output wire [6:0]  ins,")
    w("    output wire [2:0]  pn,")
    w("    output wire [2:0]  pn_s,")
    w("    output wire        s3,")
    w("    output wire [17:0] plan_type,")
    w("    output wire [17:0] plan_len")
    w(");")
    w("    reg        d_q, p_q, s3_q;")
    w("    reg [6:0]  ins_q;")
    w("    reg [2:0]  pn_q, pns_q;")
    w("    reg [17:0] pt_q, pl_q;")
    w("    assign specified  = d_q;")
    w("    assign is_prefix  = p_q;")
    w("    assign ins        = ins_q;")
    w("    assign pn         = pn_q;")
    w("    assign pn_s       = pns_q;")
    w("    assign s3         = s3_q;")
    w("    assign plan_type  = pt_q;")
    w("    assign plan_len   = pl_q;")
    w("    always @* begin")
    w("        // default: not one of the 850 specified forms, runs as NOP (OCF 4)")
    w("        d_q = 1'b0; p_q = 1'b0; s3_q = 1'b0; ins_q = 7'd%d; pn_q = 3'd1; pns_q = 3'd1;" % kinds.index("NOP"))
    w("        pt_q = 18'd0; pl_q = {14'd0, 3'd4};".replace("{14'd0, 3'd4}", "18'd4"))
    w("        case ({prefix, ir})")
    def vec(plan, which):
        v = 0
        for i, (t, l) in enumerate(plan):
            v |= (TYPES[t] if which == "t" else l) << (3 * i)
        return v
    for (pre, op), f in sorted(forms.items()):
        plan = f["plan"]
        pns, s3 = len(plan), 0
        if f["short"] is not None:
            sp = f["short"]
            if sp == plan[:len(sp)]:
                pns = len(sp)
            else:                                    # CALL cc not met: same M cycles, M3 = 3 T
                assert len(sp) == len(plan) - 2 and sp[:2] == plan[:2] and sp[2] == (plan[2][0], 3) and plan[2][1] == 4, f
                pns, s3 = len(sp), 1
        w("        {3'd%d, 8'h%02X}: begin d_q = 1'b1; ins_q = 7'd%d; pn_q = 3'd%d; pns_q = 3'd%d; s3_q = 1'b%d; pt_q = 18'o%06o; pl_q = 18'o%06o; end // %s"
          % (pre, op, f["kind"], len(plan), pns, s3, vec(plan, "t"), vec(plan, "l"), f["mnem"]))
    for pre, op in sorted(PREFIX_ONLY):
        w("        {3'd%d, 8'h%02X}: begin p_q = 1'b1; ins_q = 7'd%d; end // prefix byte" % (pre, op, kinds.index("PREFIX")))
    w("        default: ;")
    w("        endcase")
    w("    end")
    w("endmodule")
    return "\n".join(L) + "\n", "\n".join(vh) + "\n"

def main():
    ok, log = run_checks()
    txt = "\n".join(log) + "\n" + ("RESULT: PASS" if ok else "RESULT: FAIL") + "\n"
    print(txt, end="")
    v, vh = emit()
    if CHECK_ONLY:
        same = open(HERE + "/z80_decode.v").read() == v and open(HERE + "/z80_decode_kinds.vh").read() == vh
        print("committed z80_decode.v and z80_decode_kinds.vh == regenerated:", "yes" if same else "NO")
        ok &= same
    elif ok:
        open(HERE + "/z80_decode.v", "w").write(v)
        open(HERE + "/z80_decode_kinds.vh", "w").write(vh)
    sys.exit(0 if ok else 1)

main()
