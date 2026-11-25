// C7 (spec §7): bus_conflict positive case + negative cases, on the real rtl/control/z80_system.v (not the tb/z80_bus stand-in).
// Run from the repo root (prog.hex path). Harness-only: force/release on the system's pins, no RTL change.
//   Phase N (negative): reset, run tests/z80_c7/prog.hex (M1, MR, MW, PR, PW, and an INTA via int_n) with bus_conflict sampled every half: must stay 0;
//                       every driven pin (a, d_out, strobes, bus_oe, d_oe) is checked for X/Z every half after reset.
//   Phase P (positive): three runs, one per term of sys_drive, each after a reset: wait for a half with d_oe = 1 (a write), force for one clock, with the other two terms held off,
//                       mem_rd (mreq_n=rd_n=0) / io_rd (iorq_n=rd_n=0, m1_n=1, mreq_n=1) / inta (m1_n=iorq_n=0, mreq_n=rd_n=1). bus_conflict must go 1, stay 1 for 40 more clocks
//                       with the force released, and clear only when reset_n = 0. check_known is also called on the pins before each stimulus.
`timescale 1ns/1ps
/* verilator lint_off UNUSEDSIGNAL */
module tb;
  reg clk = 0, reset_n = 0, wait_n = 1, int_n = 1, nmi_n = 1, busrq_n = 1;
  wire [15:0] a; wire [7:0] d_out, con_char; wire d_oe, bus_oe, m1_n, mreq_n, iorq_n, rd_n, wr_n, rfsh_n, halt_n, busak_n, bus_conflict, con_strobe, done;
  z80_system #(.MEM_INIT("tests/z80_c7/prog.hex"), .IO_INIT(""), .CPM(0)) dut (
    .clk(clk), .reset_n(reset_n), .wait_n(wait_n), .int_n(int_n), .nmi_n(nmi_n), .busrq_n(busrq_n), .int_vector(8'hFF),
    .a(a), .d_out(d_out), .d_oe(d_oe), .bus_oe(bus_oe), .m1_n(m1_n), .mreq_n(mreq_n), .iorq_n(iorq_n), .rd_n(rd_n), .wr_n(wr_n),
    .rfsh_n(rfsh_n), .halt_n(halt_n), .busak_n(busak_n), .bus_conflict(bus_conflict), .con_char(con_char), .con_strobe(con_strobe), .done(done));
  always #5 clk = ~clk;

  integer errors = 0, h, seen_m1 = 0, seen_mr = 0, seen_mw = 0, seen_pr = 0, seen_pw = 0, seen_inta = 0, xz = 0;
  task fail(input string m); begin errors = errors + 1; $display("FAIL %s (half %0d)", m, h); end endtask

  // classify the half by the strobes (negative-phase coverage of the §6.1 cycle types)
  task classify; begin
    if (m1_n === 0 && mreq_n === 0 && rd_n === 0) seen_m1 = seen_m1 + 1;
    if (m1_n === 1 && mreq_n === 0 && rd_n === 0) seen_mr = seen_mr + 1;
    if (mreq_n === 0 && wr_n === 0) seen_mw = seen_mw + 1;
    if (m1_n === 1 && iorq_n === 0 && rd_n === 0) seen_pr = seen_pr + 1;
    if (m1_n === 1 && iorq_n === 0 && wr_n === 0) seen_pw = seen_pw + 1;
    if (m1_n === 0 && iorq_n === 0) seen_inta = seen_inta + 1;
  end endtask

  task check_known; begin
    if ((^{a, d_out, d_oe, bus_oe, m1_n, mreq_n, iorq_n, rd_n, wr_n, rfsh_n, halt_n, busak_n, bus_conflict}) === 1'bx) begin xz = xz + 1; fail("X/Z on a driven pin"); end
  end endtask

  initial begin : main
    integer k, src;
    // ---- Phase N
    repeat (4) @(posedge clk);
    @(negedge clk); reset_n = 1;
    for (h = 0; h < 400; h = h + 1) begin
      @(negedge clk);
      if (h == 120) int_n = 0;           // after EI: an INTA, then RST 38H -> HALT
      if (h == 160) int_n = 1;
      check_known; classify;
      if (bus_conflict !== 1'b0) fail("negative case: bus_conflict != 0");
    end
    $display("negative phase: 400 halves, bus_conflict=%b; cycle halves seen M1=%0d MR=%0d MW=%0d PR=%0d PW=%0d INTA=%0d; X/Z halves=%0d",
             bus_conflict, seen_m1, seen_mr, seen_mw, seen_pr, seen_pw, seen_inta, xz);
    if (!(seen_m1 > 0 && seen_mr > 0 && seen_mw > 0 && seen_pr > 0 && seen_pw > 0 && seen_inta > 0)) fail("a §6.1 cycle type was not exercised");
    // ---- Phase P: three sources of sys_drive, one run each (reset between runs so each checks stickiness on its own)
    for (src = 0; src < 3; src = src + 1) begin
      @(negedge clk); reset_n = 0; repeat (6) @(negedge clk);
      if (bus_conflict !== 1'b0) fail("bus_conflict not 0 under reset");
      @(negedge clk); reset_n = 1; int_n = 1;
      k = 0;
      while (d_oe !== 1'b1 && k < 400) begin @(negedge clk); k = k + 1; if (bus_conflict !== 1'b0) fail("bus_conflict before the stimulus"); end
      if (d_oe !== 1'b1) fail("no write half found");
      else begin
        $display("positive phase src %0d (%0s): d_oe=1 at clock %0d, bus_conflict=%b before the stimulus", src, src == 0 ? "mem_rd" : src == 1 ? "io_rd" : "inta", k, bus_conflict);
        check_known;
        case (src)
          0: begin force dut.mreq_n = 1'b0; force dut.rd_n = 1'b0; end                                // mem_rd
          1: begin force dut.iorq_n = 1'b0; force dut.rd_n = 1'b0; force dut.m1_n = 1'b1; force dut.mreq_n = 1'b1; end   // io_rd only (mreq_n held 1 so mem_rd is off)
          default: begin force dut.m1_n = 1'b0; force dut.iorq_n = 1'b0; force dut.mreq_n = 1'b1; force dut.rd_n = 1'b1; end // inta only (mem_rd, io_rd off)
        endcase
        @(negedge clk);
        release dut.mreq_n; release dut.rd_n; release dut.iorq_n; release dut.m1_n;
        if (bus_conflict !== 1'b1) fail("positive case: bus_conflict did not go 1"); else $display("src %0d: bus_conflict=1 one clock after the forced strobe in a write half", src);
        for (k = 0; k < 40; k = k + 1) begin @(negedge clk); if (bus_conflict !== 1'b1) fail("bus_conflict not sticky"); end
        $display("src %0d: sticky: bus_conflict=%b 40 clocks after the stimulus ended", src, bus_conflict);
        reset_n = 0; repeat (2) @(negedge clk);
        if (bus_conflict !== 1'b0) fail("bus_conflict not cleared by reset_n=0"); else $display("src %0d: cleared by reset_n=0", src);
      end
    end
    if (errors == 0) $display("PASS C7 (negative + positive)"); else $display("FAIL C7: %0d errors", errors);
    $finish;
  end
endmodule
