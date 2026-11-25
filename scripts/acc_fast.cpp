// Fast acceptance driver (chip-z80#72, Tesla): z80_system CPM=1 under Verilator with the clock driven from this C++ loop (no --timing).
// Same interface as sw/exerciser/z80_acc_tb.sv: +hex=<file> ($readmemh format)  +maxclk=<posedges, default 4e9>;
// con_char printed on con_strobe at posedge; reset_n low for the first 8 posedges; last line
// "[acc] done=D timeout=T bus_conflict=C half-T-clocks=N" (N counted in posedges, as the bench does).
// Difference on purpose: bus_conflict is STICKY here (1 if ever high), the bench prints the last cycle's value.
#include "Vz80_system.h"
#include "Vz80_system___024root.h"
#include "verilated.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

static bool load_hex(const char *path, Vz80_system *t) {
    FILE *f = fopen(path, "r");
    if (!f) return false;
    char tok[256];
    unsigned addr = 0;
    auto &mem = t->rootp->z80_system__DOT__u_mem__DOT__mem;
    while (fscanf(f, "%255s", tok) == 1) {
        if (tok[0] == '/' ) { int c; while ((c = fgetc(f)) != '\n' && c != EOF) {} continue; }
        if (tok[0] == '@') addr = strtoul(tok + 1, nullptr, 16);
        else { mem[addr & 0xFFFF] = (unsigned char)strtoul(tok, nullptr, 16); addr++; }
    }
    fclose(f);
    return true;
}

int main(int argc, char **argv) {
    const char *hex = nullptr;
    unsigned long long maxclk = 4000000000ULL;
    for (int i = 1; i < argc; i++) {
        if (!strncmp(argv[i], "+hex=", 5)) hex = argv[i] + 5;
        else if (!strncmp(argv[i], "+maxclk=", 8)) maxclk = strtoull(argv[i] + 8, nullptr, 10);
    }
    if (!hex) { printf("[acc] need +hex=<file>\n"); return 0; }
    Verilated::commandArgs(argc, argv);
    Vz80_system *t = new Vz80_system;
    t->clk = 0; t->reset_n = 0; t->wait_n = 1; t->int_n = 1; t->nmi_n = 1; t->busrq_n = 1; t->int_vector = 0;
    t->eval();  // runs the memory's initial block (zero fill), then we overlay the hex
    if (!load_hex(hex, t)) { printf("[acc] cannot read %s\n", hex); return 1; }
    t->eval();
    unsigned long long n = 0;
    bool timed_out = false, conflict_seen = false;
    for (;;) {
        // clk is low and settled: values sampled here are what the bench's always @(posedge clk) sees
        if (t->con_strobe) putchar(t->con_char);
        if (t->bus_conflict) conflict_seen = true;
        if (t->done || n >= maxclk) {
            if (!t->done) timed_out = true;
            printf("\n[acc] done=%d timeout=%d bus_conflict=%d half-T-clocks=%llu\n", (int)t->done, (int)timed_out, (int)conflict_seen, n);
            break;
        }
        n++;
        t->clk = 1; t->eval();
        if (n == 8) t->reset_n = 1;  // released right after the 8th posedge
        // The design has only posedge logic (grep negedge rtl/: none), so the clk=0 eval is skipped: drop clk and re-arm
        // Verilator's edge detector by hand. Saves a full combinational pass per cycle. -DACC_FULL_EVAL restores the plain two-eval loop.
#ifdef ACC_FULL_EVAL
        t->clk = 0; t->eval();
#else
        t->clk = 0; t->rootp->__Vtrigprevexpr___TOP__clk__0 = 0;
#endif
    }
    fflush(stdout);
    t->final();
    delete t;
    return 0;
}
