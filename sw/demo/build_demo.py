#!/usr/bin/env python3
"""Builds sw/demo/demo.com from the program below. Owner: Homer. Original code, ours (rule 9).
No Z80 assembler is installed in the lab, so this file IS the assembler: ~12 opcode helpers, two passes
(labels resolved on the second), each emitting the bytes straight from the Zilog Z80 opcode table (spec §5).
Writes sw/demo/demo.com and the listing sw/demo/demo.lst (address, bytes, source line).
Usage: sw/demo/build_demo.py
"""
import os, struct

ORG = 0x100
HERE = os.path.dirname(os.path.abspath(__file__))


class Asm:
    def __init__(self):
        self.labels, self.out, self.lst, self.fix = {}, bytearray(), [], []

    def pc(self):
        return ORG + len(self.out)

    def emit(self, src, *b):
        a = self.pc()
        for x in b:
            self.out += bytes([x]) if isinstance(x, int) else x
        self.lst.append((a, bytes(self.out[a - ORG:]), src))

    def label(self, n):
        self.labels[n] = self.pc()
        self.lst.append((self.pc(), b"", n + ":"))

    # --- instructions used by the demo ---
    def ld_r_n(self, r, n):  # r in B C D E H L . A
        self.emit(f"ld {'bcdehl.a'[r]},{n:#04x}", 0x06 | r << 3, n)
    def ld_rr_nn(self, rr, lab, op):  # rr: 0 BC 1 DE 2 HL; IX handled separately
        self.fix.append((len(self.out) + 1, lab, 2, False))
        self.emit(f"ld {rr},{lab}", op, 0, 0)
    def ld_ix_nn(self, lab):
        self.fix.append((len(self.out) + 2, lab, 2, False))
        self.emit(f"ld ix,{lab}", 0xDD, 0x21, 0, 0)
    def ld_a_ixd(self, d): self.emit(f"ld a,(ix+{d})", 0xDD, 0x7E, d)
    def add_a_ixd(self, d): self.emit(f"add a,(ix+{d})", 0xDD, 0x86, d)
    def ld_ixd_a(self, d): self.emit(f"ld (ix+{d}),a", 0xDD, 0x77, d)
    def jr(self, op, name, lab):
        self.fix.append((len(self.out) + 1, lab, 1, True))
        self.emit(f"{name} {lab}", op, 0)
    def call(self, lab):
        self.fix.append((len(self.out) + 1, lab, 2, False))
        self.emit(f"call {lab}", 0xCD, 0, 0)
    def resolve(self):
        for off, lab, size, rel in self.fix:
            t = self.labels[lab]
            if rel:
                d = t - (ORG + off + 1)
                assert -128 <= d < 128, lab
                self.out[off] = d & 255
            else:
                self.out[off:off + 2] = struct.pack("<H", t)
        # patch listing bytes
        self.lst = [(a, bytes(self.out[a - ORG:a - ORG + len(b)]), s) for a, b, s in self.lst]


a = Asm()
E, C, B, A = 3, 1, 0, 7
BDOS = 0x0005


def puts(lab):
    a.ld_rr_nn("de", lab, 0x11)
    a.ld_r_n(C, 9)
    a.call("bdos")


# ---- main ----
puts("banner")
# 1. LDIR: copy the "copied" string to buf, then print buf
a.ld_rr_nn("hl", "src", 0x21)
a.ld_rr_nn("de", "buf", 0x11)
a.emit("ld bc,SRCLEN", 0x01, 0, 0)
srclen_off = len(a.out) - 2
a.emit("ldir", 0xED, 0xB0)
puts("buf")
# 2. IX indexed: sum the 8-byte table with ld a,(ix+0) / add a,(ix+d); store the sum with ld (ix+8),a
puts("m_ix")
a.ld_ix_nn("tbl")
a.ld_a_ixd(0)
for d in range(1, 8):
    a.add_a_ixd(d)
a.ld_ixd_a(8)
a.call("hex")
a.ld_r_n(E, 13); a.ld_r_n(C, 2); a.call("bdos")
a.ld_r_n(E, 10); a.ld_r_n(C, 2); a.call("bdos")
# 3. DJNZ: count 0..9
puts("m_dj")
a.ld_r_n(B, 10)
a.ld_r_n(E, ord("0"))
a.label("dj")
a.emit("push bc", 0xC5)
a.ld_r_n(C, 2)
a.call("bdos")
a.emit("pop bc", 0xC1)
a.emit("inc e", 0x1C)
a.jr(0x10, "djnz", "dj")
puts("crlf")
puts("done")
a.emit("jp 0000h", 0xC3, 0, 0)            # CP/M warm boot: the bench stops here
# ---- subroutines ----
a.label("bdos")
a.emit("jp 0005h", 0xC3, 5, 0)
a.label("hex")                               # print A as two hex digits
a.emit("push af", 0xF5)
for _ in range(4):
    a.emit("rrca", 0x0F)
a.call("nib")
a.emit("pop af", 0xF1)
a.label("nib")
a.emit("and 0fh", 0xE6, 0x0F)
a.emit("add a,'0'", 0xC6, 0x30)
a.emit("cp ':'", 0xFE, 0x3A)
a.jr(0x38, "jr c", "nib_ok")
a.emit("add a,7", 0xC6, 0x07)
a.label("nib_ok")
a.emit("ld e,a", 0x5F)
a.ld_r_n(C, 2)
a.emit("call 0005h", 0xCD, 5, 0)
a.emit("ret", 0xC9)
# ---- data ----
def db(name, s):
    a.label(name)
    a.emit(f"db {s!r}", s if isinstance(s, bytes) else s.encode())

db("banner", "TuriChips Z80 demo\r\n$")
db("m_ix", "IX sum of 10,20..80 = $")
db("m_dj", "DJNZ count: $")
db("crlf", "\r\n$")
db("done", "Demo finished.\r\n$")
a.label("src")
msg = b"LDIR copied this string.\r\n$"
a.emit("db 'LDIR copied this string.',13,10,'$'", msg)
a.label("tbl")
a.emit("db 10,20,30,40,50,60,70,80,0", bytes([10, 20, 30, 40, 50, 60, 70, 80, 0]))
a.label("buf")
a.emit(f"ds {len(msg)}", bytes(len(msg)))
a.out[srclen_off:srclen_off + 2] = struct.pack("<H", len(msg))
a.resolve()
open(f"{HERE}/demo.com", "wb").write(a.out)
with open(f"{HERE}/demo.lst", "w") as f:
    for ad, b, s in a.lst:
        f.write(f"{ad:04X}  {b[:4].hex(' '):<12} {s}\n" if b else f"{ad:04X}  {'':<12} {s}\n")
print(f"demo.com {len(a.out)} bytes")
